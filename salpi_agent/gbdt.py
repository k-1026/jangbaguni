"""numpy만 쓰는 작은 그래디언트 부스팅 (LightGBM 방식을 줄여 옮김).

- 히스토그램 분할: 요인마다 학습 자료의 분위수로 최대 32칸, 빈 값(NaN)은 따로 한 칸
- 목표: "l1" (절대오차 — 평균 오차와 같은 기준) · "l2" (제곱오차)
  l1 은 잎 값을 그 잎에 든 남은 오차의 중앙값으로 정함 (LightGBM 의 l1 과 같은 방식)
- 범주 요인(품목)은 마디마다 범주를 기울기 평균 순으로 줄 세운 뒤 나눔
- 왜 직접 만들었나: 이 PC의 보안 정책이 LightGBM · scikit-learn 의 DLL 을 막음. 외부 라이브러리 없이 돌아가서
  GitHub Actions 같은 곳에서도 설치 걱정이 없음
"""
import numpy as np


class _Binner:
    def __init__(self, X, cat_cols, n_bins=32):
        self.cat_cols = set(cat_cols)
        self.edges = []
        for f in range(X.shape[1]):
            x = X[:, f]
            x = x[np.isfinite(x)]
            if f in self.cat_cols or len(x) == 0:
                self.edges.append(None)
                continue
            qs = np.unique(np.quantile(x, np.linspace(0, 1, n_bins + 1)[1:-1]))
            self.edges.append(qs)

    def transform(self, X):
        out = np.empty(X.shape, dtype=np.int32)
        for f in range(X.shape[1]):
            x = X[:, f]
            if self.edges[f] is None:   # 범주: 값 그대로 (0..), 빈 값은 맨 끝
                b = np.where(np.isfinite(x), x, -1).astype(np.int32)
                out[:, f] = np.where(b < 0, 63, b)
            else:
                b = np.searchsorted(self.edges[f], np.where(np.isfinite(x), x, 0), side="right").astype(np.int32)
                out[:, f] = np.where(np.isfinite(x), b, 63)   # 63 = 빈 값 칸
        return out


class GBDT:
    def __init__(self, objective="l1", learning_rate=0.05, max_depth=4, min_leaf=150, n_rounds=2000,
                 subsample=0.8, colsample=0.8, l2=5.0, cat_cols=(), seed=7):
        self.__dict__.update(locals())
        del self.__dict__["self"]
        self.trees = []

    # --- 나무 하나 ---
    def _best_split(self, Bn, g, idx, feats):
        G, n = g[idx].sum(), len(idx)
        base = G * G / (n + self.l2)
        best = (0.0, None)
        for f in feats:
            b = Bn[idx, f]
            gs = np.bincount(b, weights=g[idx], minlength=64)
            cs = np.bincount(b, minlength=64).astype(float)
            used = np.nonzero(cs)[0]
            if len(used) < 2:
                continue
            if f in self.cat_cols:
                order = used[np.argsort(gs[used] / cs[used])]
            else:
                order = used                      # 숫자 칸은 원래 순서 (빈 값 칸 63은 맨 오른쪽)
            gl, cl = np.cumsum(gs[order])[:-1], np.cumsum(cs[order])[:-1]
            gr, cr = G - gl, n - cl
            ok = (cl >= self.min_leaf) & (cr >= self.min_leaf)
            if not ok.any():
                continue
            gain = np.where(ok, gl * gl / (cl + self.l2) + gr * gr / (cr + self.l2) - base, -np.inf)
            k = int(np.argmax(gain))
            if gain[k] > best[0]:
                best = (gain[k], (f, set(order[: k + 1].tolist())))
        return best[1]

    def _grow(self, Bn, g, resid, idx, depth, feats):
        split = self._best_split(Bn, g, idx, feats) if depth < self.max_depth else None
        if split is None:
            r = resid[idx]
            val = np.median(r) if self.objective == "l1" else r.sum() / (len(r) + self.l2)
            return ("leaf", float(val))
        f, left_bins = split
        mask = np.isin(Bn[idx, f], list(left_bins))
        return ("node", f, left_bins, self._grow(Bn, g, resid, idx[mask], depth + 1, feats),
                self._grow(Bn, g, resid, idx[~mask], depth + 1, feats))

    @staticmethod
    def _apply(tree, Bn):
        out = np.empty(len(Bn))
        stack = [(tree, np.arange(len(Bn)))]
        while stack:
            t, idx = stack.pop()
            if t[0] == "leaf":
                out[idx] = t[1]
                continue
            mask = np.isin(Bn[idx, t[1]], list(t[2]))
            stack.append((t[3], idx[mask]))
            stack.append((t[4], idx[~mask]))
        return out

    # --- 학습 ---
    def fit(self, X, y, X_val=None, y_val=None, early_stop=100):
        rng = np.random.default_rng(self.seed)
        self.binner = _Binner(X, self.cat_cols)
        Bn = self.binner.transform(X)
        Bv = self.binner.transform(X_val) if X_val is not None else None
        self.init = float(np.median(y)) if self.objective == "l1" else float(np.mean(y))
        pred = np.full(len(y), self.init)
        pv = np.full(len(y_val), self.init) if X_val is not None else None
        best_loss, best_n, self.trees = np.inf, 0, []
        n_feat = X.shape[1]
        for it in range(self.n_rounds):
            resid = y - pred
            g = np.sign(resid) if self.objective == "l1" else resid
            idx = np.sort(rng.choice(len(y), int(len(y) * self.subsample), replace=False))
            feats = rng.choice(n_feat, max(1, int(n_feat * self.colsample)), replace=False)
            tree = self._grow(Bn, g, resid, idx, 0, feats)
            self.trees.append(tree)
            pred += self.learning_rate * self._apply(tree, Bn)
            if pv is not None:
                pv += self.learning_rate * self._apply(tree, Bv)
                loss = np.abs(y_val - pv).mean() if self.objective == "l1" else ((y_val - pv) ** 2).mean()
                if loss < best_loss - 1e-9:
                    best_loss, best_n = loss, it + 1
                elif it + 1 - best_n >= early_stop:
                    break
        if pv is not None:
            self.trees = self.trees[:best_n]
        self.best_iteration = len(self.trees)
        return self

    def predict(self, X):
        Bn = self.binner.transform(X)
        out = np.full(len(X), self.init)
        for t in self.trees:
            out += self.learning_rate * self._apply(t, Bn)
        return out

    def importance(self, n_features):
        """요인별로 몇 번 나누는 데 쓰였나 (간단한 중요도)."""
        cnt = np.zeros(n_features)
        stack = list(self.trees)
        while stack:
            t = stack.pop()
            if t[0] == "node":
                cnt[t[1]] += 1
                stack += [t[3], t[4]]
        return cnt
