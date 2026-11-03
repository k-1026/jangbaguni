-- 살피 DB 스키마 (Supabase / PostgreSQL)
-- 실행: Supabase 대시보드 → SQL Editor에 전체 붙여 넣고 Run → 그다음 seed.sql
-- 근거: brand/살피_브랜드키트_기획서.md 11-4 도구 목록 · 11-5 필수 데이터 · 3-3 행동 이벤트
-- 다시 실행해도 안전하도록 if not exists / drop policy if exists 사용

-- =========================================================
-- C. 기준 정보 (팀이 만드는 데이터)
-- =========================================================

-- 품목 마스터: 레시피·영수증·시세를 하나의 품목으로 묶는 기준
create table if not exists items (
  id                  bigint generated always as identity primary key,
  name                text not null unique,                 -- 표준 품목명 (예: 양파)
  category            text not null,                        -- 채소 / 육류 / 두부·가공 / 양념 / 곡물
  base_unit           text not null default 'kg',           -- 레시피·단가 계산 단위 (kg, 모, 개)
  storage_type        text not null default '신선'
                      check (storage_type in ('신선', '냉장', '냉동', '건자재')),
  price_comparable    boolean not null default false,       -- 국산 비중이 높아 도매 시세와 비교 가능한가
  kamis_category_code text,                                 -- KAMIS p_itemcategorycode
  kamis_item_code     text,                                 -- KAMIS p_itemcode
  kamis_kind_code     text,                                 -- KAMIS p_kindcode
  at_gds_sclsf_cd     text,                                 -- aT 정산정보 품목 소분류 코드
  note                text
);

-- 영수증 품목 매핑표: OCR로 읽은 이름 → 품목 마스터 ("깐양파 15kg" → 양파 15kg)
create table if not exists item_aliases (
  id                bigint generated always as identity primary key,
  alias             text not null unique,
  item_id           bigint not null references items(id) on delete cascade,
  base_qty_per_unit numeric(10,3) not null default 1        -- 영수증 1개 = 기준단위 몇 개
);

-- =========================================================
-- B. 외부 데이터 (공식 API 수집)
-- =========================================================

-- aT 전국 공영도매시장 정산정보 (경락가 · 반입량), 대구 북부 = 220001
create table if not exists wholesale_prices (
  id            bigint generated always as identity primary key,
  trade_date    date not null,                              -- trd_clcln_ymd
  whsl_mrkt_cd  text not null default '220001',
  item_id       bigint references items(id),
  gds_sclsf_cd  text,
  gds_sclsf_nm  text,
  grade_nm      text,                                       -- grd_nm
  unit_qty      numeric(10,3),                              -- unit_qty
  unit_nm       text,                                       -- unit_nm (kg 등)
  avg_price     numeric(12,2),                              -- avgprc
  low_price     numeric(12,2),                              -- lwprc
  high_price    numeric(12,2),                              -- hgprc
  total_qty     numeric(14,3),                              -- unit_tot_qty (반입량)
  source        text not null default 'api',                -- api / demo
  collected_at  timestamptz not null default now(),
  unique nulls not distinct (trade_date, whsl_mrkt_cd, gds_sclsf_cd, grade_nm, unit_qty, unit_nm)
);
create index if not exists wholesale_prices_item_date on wholesale_prices (item_id, trade_date desc);

-- KAMIS 도·소매가, 대구 = 2200
create table if not exists kamis_prices (
  id            bigint generated always as identity primary key,
  price_date    date not null,
  product_cls   text not null check (product_cls in ('소매', '도매')),  -- p_productclscode 01/02
  item_id       bigint references items(id),
  item_code     text not null,
  kind_code     text not null,
  rank_code     text not null default '04',                 -- 04 상품 / 05 중품
  country_code  text not null default '2200',
  market_name   text not null default '',                   -- 칠성 · 서문 · 북부도매 등
  unit          text,
  price         numeric(12,2),
  source        text not null default 'api',
  collected_at  timestamptz not null default now(),
  unique (price_date, product_cls, item_code, kind_code, rank_code, country_code, market_name)
);
create index if not exists kamis_prices_item_date on kamis_prices (item_id, price_date desc);

-- 기상청 ASOS 일자료, 대구 = 143
create table if not exists weather_daily (
  obs_date       date not null,
  stn_id         text not null default '143',
  avg_temp       numeric(5,1),                              -- avgTa
  min_temp       numeric(5,1),                              -- minTa
  max_temp       numeric(5,1),                              -- maxTa
  precipitation  numeric(6,1),                              -- sumRn (mm)
  avg_humidity   numeric(5,1),                              -- avgRhm
  collected_at   timestamptz not null default now(),
  primary key (obs_date, stn_id)
);

-- 한국천문연구원 특일 정보 (공휴일 · 기념일 · 절기)
create table if not exists special_days (
  locdate     date not null,
  date_name   text not null,
  is_holiday  boolean not null default false,               -- isHoliday = 'Y'
  date_kind   text,                                         -- 국경일·공휴일 / 기념일 / 24절기 / 잡절
  source      text not null default 'api',
  primary key (locdate, date_name)
);

-- 한국관광공사 국문 관광정보 — 대구(lDongRegnCd 27) 행사·축제
create table if not exists local_events (
  content_id     text primary key,                          -- contentid
  title          text not null,
  start_date     date,                                      -- eventstartdate
  end_date       date,                                      -- eventenddate
  addr           text,                                      -- addr1
  ldong_regn_cd  text not null default '27',
  ldong_signgu_cd text,                                     -- 구·군 코드
  map_x          numeric(12,8),
  map_y          numeric(12,8),
  collected_at   timestamptz not null default now()
);
create index if not exists local_events_dates on local_events (start_date, end_date);

-- =========================================================
-- A. 우리 가게 데이터
-- =========================================================

create table if not exists stores (
  id                  uuid primary key default gen_random_uuid(),
  owner_id            uuid references auth.users(id) on delete cascade,
  name                text not null,
  business_type       text not null default '한식',
  district            text,                                 -- 대구 구·군 (예: 달서구)
  seats               int,
  delivery_ratio      numeric(4,3),                         -- 배달 비중 0~1
  open_days           text[] default array['월','화','수','목','금','토'],
  main_supplier       text,
  restock_cycle_days  int default 7,                        -- 입고 주기
  segment             text check (segment in ('S1','S2','S3','S4','S5')),
  is_demo             boolean not null default false,       -- 시연용 가상 매장 (누구나 조회 가능)
  created_at          timestamptz not null default now()
);

create table if not exists menus (
  id          bigint generated always as identity primary key,
  store_id    uuid not null references stores(id) on delete cascade,
  name        text not null,
  price       int not null,                                 -- 판매가 (원)
  category    text,
  is_active   boolean not null default true,
  unique (store_id, name)
);

-- 레시피: 메뉴 1인분에 들어가는 재료량 (품목 base_unit 기준)
create table if not exists recipe_items (
  menu_id          bigint not null references menus(id) on delete cascade,
  item_id          bigint not null references items(id),
  qty_per_serving  numeric(10,4) not null,                  -- 예: 양파 0.08 (kg)
  loss_rate        numeric(4,3) not null default 0          -- 손질 손실률 0~1
                   check (loss_rate >= 0 and loss_rate < 1),
  primary key (menu_id, item_id)
);

-- 메뉴별 판매량 (POS · 배달앱 정산 · 직접 입력)
create table if not exists sales_daily (
  store_id   uuid not null references stores(id) on delete cascade,
  menu_id    bigint not null references menus(id) on delete cascade,
  sale_date  date not null,
  channel    text not null default '홀' check (channel in ('홀', '배달')),
  qty        int not null check (qty >= 0),
  primary key (store_id, menu_id, sale_date, channel)
);

-- 영수증 (실구매 기록)
create table if not exists purchases (
  id            bigint generated always as identity primary key,
  store_id      uuid not null references stores(id) on delete cascade,
  purchased_on  date not null,
  supplier      text,                                       -- 식봄 / 마트 / 도매상 등
  total_amount  int,
  source        text not null default 'ocr' check (source in ('ocr', 'manual', 'demo')),
  image_path    text,                                       -- Supabase Storage 경로
  created_at    timestamptz not null default now()
);

create table if not exists purchase_items (
  id              bigint generated always as identity primary key,
  purchase_id     bigint not null references purchases(id) on delete cascade,
  item_id         bigint references items(id),              -- 매핑 실패 시 null
  raw_name        text not null,                            -- OCR 원문
  qty_base        numeric(10,3) not null,                   -- 기준단위 수량 (kg · 모)
  amount          int not null,                             -- 합계 금액 (원)
  unit_price_base numeric(12,2) generated always as (amount / nullif(qty_base, 0)) stored
);
create index if not exists purchase_items_item on purchase_items (item_id);

-- 재고 (발주 전 "남은 양" 입력)
create table if not exists inventory (
  store_id            uuid not null references stores(id) on delete cascade,
  item_id             bigint not null references items(id),
  on_hand_qty         numeric(10,3) not null default 0,
  next_delivery_date  date,
  updated_at          timestamptz not null default now(),
  primary key (store_id, item_id)
);

-- =========================================================
-- 계산 도구 결과 · 알림 · 행동 로그
-- =========================================================

-- forecast_menu_demand 결과
create table if not exists menu_forecasts (
  store_id       uuid not null references stores(id) on delete cascade,
  menu_id        bigint not null references menus(id) on delete cascade,
  target_date    date not null,
  predicted_qty  int not null,
  lower_qty      int,
  upper_qty      int,
  contributions  jsonb,                                     -- explain_contribution (예: {"금요일":0.38,"비":0.26})
  model_version  text,
  created_at     timestamptz not null default now(),
  primary key (store_id, menu_id, target_date)
);

-- recommend_order_qty + judge_wait_or_buy 결과
create table if not exists order_recommendations (
  id               bigint generated always as identity primary key,
  store_id         uuid not null references stores(id) on delete cascade,
  item_id          bigint not null references items(id),
  target_date      date not null,
  recommended_qty  numeric(10,3) not null,
  decision         text not null check (decision in ('지금 사기', '기다리기', '나눠 사기')),
  reason           jsonb,
  created_at       timestamptz not null default now(),
  unique (store_id, item_id, target_date)
);

create table if not exists alerts (
  id          bigint generated always as identity primary key,
  store_id    uuid not null references stores(id) on delete cascade,
  kind        text not null check (kind in ('가격 급등', '원가율', '기다리기', '재고 부족')),
  message     text not null,                                -- 살피 말투, 정보 1개 + 행동 1개
  sent_at     timestamptz not null default now(),
  clicked_at  timestamptz
);

-- 3-3 행동 이벤트 로그 (세그먼트 S1~S5 계산 재료)
create table if not exists event_logs (
  id          bigint generated always as identity primary key,
  store_id    uuid not null references stores(id) on delete cascade,
  event_type  text not null check (event_type in (
                'forecast_view', 'order_recommend_shown', 'order_placed',
                'alert_sent', 'alert_clicked', 'stockout_report', 'waste_report',
                'deeplink_click', 'receipt_upload', 'menu_action_accept', 'feedback_rating')),
  payload     jsonb not null default '{}',
  created_at  timestamptz not null default now()
);
create index if not exists event_logs_store_time on event_logs (store_id, created_at desc);

-- =========================================================
-- 뷰: 메뉴 원가율 (calc_menu_cost_ratio)
-- =========================================================

-- 품목별 우리 가게 최근 실구매 단가 (get_my_purchase_price)
create or replace view v_latest_purchase_price with (security_invoker = true) as
select distinct on (p.store_id, pi.item_id)
  p.store_id, pi.item_id, i.name as item_name, i.base_unit,
  pi.unit_price_base, p.purchased_on, p.supplier
from purchase_items pi
join purchases p on p.id = pi.purchase_id
join items i on i.id = pi.item_id
where pi.item_id is not null
order by p.store_id, pi.item_id, p.purchased_on desc, pi.id desc;

-- 메뉴 1인분 원가 · 원가율 (단가 없는 재료 수도 함께 표시)
create or replace view v_menu_cost_ratio with (security_invoker = true) as
select
  m.store_id, m.id as menu_id, m.name as menu_name, m.price,
  round(sum(r.qty_per_serving / (1 - r.loss_rate) * lp.unit_price_base)) as cost_per_serving,
  round(sum(r.qty_per_serving / (1 - r.loss_rate) * lp.unit_price_base) / m.price * 100, 1) as cost_ratio_pct,
  count(*) filter (where lp.unit_price_base is null) as items_without_price
from menus m
join recipe_items r on r.menu_id = m.id
left join v_latest_purchase_price lp on lp.store_id = m.store_id and lp.item_id = r.item_id
where m.is_active
group by m.store_id, m.id, m.name, m.price;

-- =========================================================
-- 접근 권한 (RLS)
-- 외부·기준 데이터: 누구나 읽기, 쓰기는 수집 스크립트(service_role)만
-- 가게 데이터: 가게 주인만 읽기·쓰기, 시연용 매장(is_demo)은 누구나 읽기
-- =========================================================

do $$
declare t text;
begin
  foreach t in array array['items','item_aliases','wholesale_prices','kamis_prices',
                           'weather_daily','special_days','local_events'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
  end loop;
end $$;

alter table stores enable row level security;
drop policy if exists "owner or demo read" on stores;
create policy "owner or demo read" on stores for select
  using (owner_id = auth.uid() or is_demo);
drop policy if exists "owner write" on stores;
create policy "owner write" on stores for all to authenticated
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());

do $$
declare t text;
begin
  foreach t in array array['menus','sales_daily','purchases','inventory',
                           'menu_forecasts','order_recommendations','alerts','event_logs'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "store read" on %I', t);
    execute format('create policy "store read" on %I for select using (
      store_id in (select id from stores where owner_id = auth.uid() or is_demo))', t);
    execute format('drop policy if exists "store write" on %I', t);
    execute format('create policy "store write" on %I for all to authenticated
      using (store_id in (select id from stores where owner_id = auth.uid()))
      with check (store_id in (select id from stores where owner_id = auth.uid()))', t);
  end loop;
end $$;

-- store_id가 없는 하위 표는 상위 표를 따라감
alter table recipe_items enable row level security;
drop policy if exists "store read" on recipe_items;
create policy "store read" on recipe_items for select using (
  menu_id in (select id from menus));                      -- menus의 RLS가 그대로 적용됨
drop policy if exists "store write" on recipe_items;
create policy "store write" on recipe_items for all to authenticated
  using (menu_id in (select m.id from menus m join stores s on s.id = m.store_id where s.owner_id = auth.uid()))
  with check (menu_id in (select m.id from menus m join stores s on s.id = m.store_id where s.owner_id = auth.uid()));

alter table purchase_items enable row level security;
drop policy if exists "store read" on purchase_items;
create policy "store read" on purchase_items for select using (
  purchase_id in (select id from purchases));               -- purchases의 RLS가 그대로 적용됨
drop policy if exists "store write" on purchase_items;
create policy "store write" on purchase_items for all to authenticated
  using (purchase_id in (select p.id from purchases p join stores s on s.id = p.store_id where s.owner_id = auth.uid()))
  with check (purchase_id in (select p.id from purchases p join stores s on s.id = p.store_id where s.owner_id = auth.uid()));
