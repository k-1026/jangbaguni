-- 살피 시드 데이터 (schema.sql 실행 후 실행)
-- 기준 정보(품목 · 매핑 · 2026 하반기 공휴일) + 11/4 시연용 가상 한식당 1곳
-- 가상 데이터는 stores.is_demo = true, source = 'demo'로 표시 → 실데이터와 구분·삭제 가능
-- 다시 실행해도 중복되지 않음 (on conflict do nothing)

-- =========================================================
-- 품목 마스터
-- KAMIS 코드는 research/industry_food/1028_data_collection_detail.json에서 확인된 값만 기재
-- price_comparable: 국산 비중이 높은 채소만 true (기획서 7장 '한계와 대응')
-- =========================================================
insert into items (name, category, base_unit, storage_type, price_comparable,
                   kamis_category_code, kamis_item_code, kamis_kind_code, note) values
  ('양배추',     '채소',     'kg', '신선',   true,  '200', '212', '00', null),
  ('대파',       '채소',     'kg', '신선',   true,  '200', '246', '00', null),
  ('양파',       '채소',     'kg', '신선',   true,  '200', '245', '00', null),
  ('당근',       '채소',     'kg', '신선',   true,  '200', '232', '01', '품종 01(무세척)만 도매 데이터 있음'),
  ('청양고추',   '채소',     'kg', '신선',   true,  '200', '242', '03', null),
  ('깻잎',       '채소',     'kg', '신선',   true,  '200', '253', '00', null),
  ('깐마늘',     '채소',     'kg', '냉장',   false, '200', '258', '01', '대구 도매 데이터 없음, 소매만'),
  ('건고추',     '양념',     'kg', '건자재', false, '200', '241', '00', null),
  ('고춧가루',   '양념',     'kg', '건자재', false, '200', '248', '00', '국산 00 / 중국 01. 실구매가 추이만 추적'),
  ('쌀',         '곡물',     'kg', '건자재', false, '100', '111', '01', null),
  ('애호박',     '채소',     'kg', '신선',   true,  null,  null,  null, 'KAMIS 코드 확인 필요'),
  ('감자',       '채소',     'kg', '신선',   true,  null,  null,  null, 'KAMIS 코드 확인 필요'),
  ('돼지고기 앞다리', '육류', 'kg', '냉장',  false, null,  null,  null, '실구매가 추이만 추적'),
  ('두부',       '두부·가공', '모', '냉장',  false, null,  null,  null, null),
  ('배추김치',   '두부·가공', 'kg', '냉장',  false, null,  null,  null, '수입 비중 높음, 실구매가 추이만 추적'),
  ('된장',       '양념',     'kg', '건자재', false, null,  null,  null, null),
  ('고추장',     '양념',     'kg', '건자재', false, null,  null,  null, null)
on conflict (name) do nothing;

-- 영수증 품목 매핑 (OCR 원문 → 품목, 영수증 1개 = 기준단위 몇 개)
insert into item_aliases (alias, item_id, base_qty_per_unit)
select a.alias, i.id, a.qty
from (values
  ('깐양파 15kg',        '양파',            15),
  ('양파 1망(15kg)',     '양파',            15),
  ('대파 1단',           '대파',            1),
  ('대파 1kg',           '대파',            1),
  ('청양고추 1kg',       '청양고추',        1),
  ('애호박 1개',         '애호박',          0.3),
  ('감자 10kg',          '감자',            10),
  ('돈앞다리 1kg',       '돼지고기 앞다리', 1),
  ('국산두부 1모',       '두부',            1),
  ('포기김치 10kg',      '배추김치',        10),
  ('재래된장 2kg',       '된장',            2),
  ('태양초고추장 3kg',   '고추장',          3),
  ('고춧가루(중국) 1kg', '고춧가루',        1),
  ('깐마늘 1kg',         '깐마늘',          1),
  ('쌀 20kg',            '쌀',              20)
) as a(alias, item_name, qty)
join items i on i.name = a.item_name
on conflict (alias) do nothing;

-- =========================================================
-- 2026년 9월~12월 공휴일 (특일 정보 API로 수집하면 같은 키로 덮어씀)
-- =========================================================
insert into special_days (locdate, date_name, is_holiday, date_kind, source) values
  ('2026-09-24', '추석',         true, '국경일·공휴일', 'seed'),
  ('2026-09-25', '추석',         true, '국경일·공휴일', 'seed'),
  ('2026-09-26', '추석',         true, '국경일·공휴일', 'seed'),
  ('2026-10-03', '개천절',       true, '국경일·공휴일', 'seed'),
  ('2026-10-05', '대체공휴일',   true, '국경일·공휴일', 'seed'),
  ('2026-10-09', '한글날',       true, '국경일·공휴일', 'seed'),
  ('2026-12-25', '기독탄신일',   true, '국경일·공휴일', 'seed')
on conflict do nothing;

-- =========================================================
-- 시연용 가상 매장 (기획서 P1 페르소나: 대구 달서구 한식당)
-- =========================================================
insert into stores (id, owner_id, name, business_type, district, seats, delivery_ratio,
                    main_supplier, restock_cycle_days, segment, is_demo)
values ('00000000-0000-0000-0000-000000000001', null, '살피 시연 한식당', '한식', '달서구',
        40, 0.300, '동네 식자재 도매상', 7, 'S2', true)
on conflict (id) do nothing;

insert into menus (store_id, name, price, category)
values ('00000000-0000-0000-0000-000000000001', '김치찌개', 9000,  '찌개'),
       ('00000000-0000-0000-0000-000000000001', '제육볶음', 10000, '볶음'),
       ('00000000-0000-0000-0000-000000000001', '된장찌개', 8000,  '찌개')
on conflict (store_id, name) do nothing;

-- 1인분 레시피. 기획서 화면 예시(김치 120 · 제육 80 · 된장 60그릇 →
-- 돼지고기 12kg · 양파 9.1kg · 두부 45모)와 맞도록 맞춘 가상 값
insert into recipe_items (menu_id, item_id, qty_per_serving, loss_rate)
select m.id, i.id, r.qty, r.loss
from (values
  ('김치찌개', '배추김치',        0.150,  0),
  ('김치찌개', '돼지고기 앞다리', 0.020,  0),
  ('김치찌개', '두부',            0.25,   0),
  ('김치찌개', '양파',            0.0075, 0),
  ('김치찌개', '대파',            0.010,  0.10),
  ('김치찌개', '고춧가루',        0.005,  0),
  ('제육볶음', '돼지고기 앞다리', 0.120,  0),
  ('제육볶음', '양파',            0.080,  0),
  ('제육볶음', '대파',            0.020,  0.10),
  ('제육볶음', '청양고추',        0.005,  0),
  ('제육볶음', '고추장',          0.030,  0),
  ('제육볶음', '고춧가루',        0.008,  0),
  ('제육볶음', '깐마늘',          0.010,  0),
  ('된장찌개', '된장',            0.040,  0),
  ('된장찌개', '두부',            0.25,   0),
  ('된장찌개', '애호박',          0.050,  0.05),
  ('된장찌개', '감자',            0.050,  0.15),
  ('된장찌개', '양파',            0.030,  0),
  ('된장찌개', '청양고추',        0.003,  0)
) as r(menu_name, item_name, qty, loss)
join menus m on m.name = r.menu_name and m.store_id = '00000000-0000-0000-0000-000000000001'
join items i on i.name = r.item_name
on conflict (menu_id, item_id) do nothing;

-- 판매량 2026-09-01 ~ 2026-11-02 (일요일 휴무)
-- 요일 효과(금 ↑ · 토 ↑ · 월 ↓) + 공휴일 ↓ + 고정 흔들림, 홀 70% · 배달 30%
insert into sales_daily (store_id, menu_id, sale_date, channel, qty)
select m.store_id, m.id, d::date, c.channel,
       greatest(0, round(
         b.base
         * case extract(isodow from d) when 1 then 0.90 when 5 then 1.25 when 6 then 1.15 else 1.0 end
         * case when exists (select 1 from special_days s where s.locdate = d::date and s.is_holiday) then 0.6 else 1.0 end
         * c.share
         + ((extract(doy from d)::int * 7 + m.id::int * 13) % 11 - 5) * c.share
       ))::int
from generate_series('2026-09-01'::date, '2026-11-02'::date, interval '1 day') d
cross join menus m
join (values ('김치찌개', 100), ('제육볶음', 68), ('된장찌개', 50)) as b(menu_name, base) on b.menu_name = m.name
cross join (values ('홀', 0.7), ('배달', 0.3)) as c(channel, share)
where m.store_id = '00000000-0000-0000-0000-000000000001'
  and extract(isodow from d) <> 7
on conflict do nothing;

-- 영수증 4장: 양파 · 돼지고기 단가가 오르는 흐름 → 제육볶음 원가율 상승 시연
insert into purchases (store_id, purchased_on, supplier, total_amount, source)
select '00000000-0000-0000-0000-000000000001', v.d::date, v.supplier, v.total, 'demo'
from (values ('2026-10-12', '동네 식자재 도매상', 0),
             ('2026-10-19', '동네 식자재 도매상', 0),
             ('2026-10-26', '동네 식자재 도매상', 0),
             ('2026-11-02', '동네 식자재 도매상', 0)) as v(d, supplier, total)
where not exists (select 1 from purchases p
                  where p.store_id = '00000000-0000-0000-0000-000000000001' and p.source = 'demo');

insert into purchase_items (purchase_id, item_id, raw_name, qty_base, amount)
select p.id, a.item_id, l.raw_name, l.cnt * a.base_qty_per_unit, l.amount
from (values
  ('2026-10-12', '깐양파 15kg',        1, 19500),
  ('2026-10-12', '돈앞다리 1kg',      12, 138000),
  ('2026-10-12', '국산두부 1모',      45, 54000),
  ('2026-10-12', '포기김치 10kg',      2, 76000),
  ('2026-10-12', '대파 1kg',           3, 9000),
  ('2026-10-12', '청양고추 1kg',       1, 9500),
  ('2026-10-12', '애호박 1개',        10, 15000),
  ('2026-10-12', '감자 10kg',          1, 26000),
  ('2026-10-12', '재래된장 2kg',       1, 14000),
  ('2026-10-12', '태양초고추장 3kg',   1, 21000),
  ('2026-10-12', '고춧가루(중국) 1kg', 1, 14000),
  ('2026-10-12', '깐마늘 1kg',         1, 11000),
  ('2026-10-19', '깐양파 15kg',        1, 22500),
  ('2026-10-19', '돈앞다리 1kg',      12, 144000),
  ('2026-10-19', '국산두부 1모',      45, 54000),
  ('2026-10-19', '대파 1kg',           3, 9600),
  ('2026-10-26', '깐양파 15kg',        1, 25500),
  ('2026-10-26', '돈앞다리 1kg',      12, 150000),
  ('2026-10-26', '국산두부 1모',      45, 54000),
  ('2026-10-26', '포기김치 10kg',      2, 76000),
  ('2026-11-02', '깐양파 15kg',        1, 28500),
  ('2026-11-02', '돈앞다리 1kg',      12, 153600),
  ('2026-11-02', '대파 1kg',           3, 10500)
) as l(d, raw_name, cnt, amount)
join item_aliases a on a.alias = l.raw_name
join purchases p on p.purchased_on = l.d::date
                and p.store_id = '00000000-0000-0000-0000-000000000001' and p.source = 'demo'
where not exists (select 1 from purchase_items pi where pi.purchase_id = p.id);

update purchases p
set total_amount = s.total
from (select purchase_id, sum(amount) as total from purchase_items group by purchase_id) s
where s.purchase_id = p.id and p.source = 'demo';

-- 현재 재고 (11/3 발주 전 입력)
insert into inventory (store_id, item_id, on_hand_qty, next_delivery_date)
select '00000000-0000-0000-0000-000000000001', i.id, v.qty, '2026-11-09'
from (values ('양파', 4.5), ('돼지고기 앞다리', 3.0), ('두부', 12), ('배추김치', 8.0),
             ('대파', 1.2), ('청양고추', 0.4), ('애호박', 0.9), ('감자', 3.5),
             ('된장', 1.1), ('고추장', 1.5), ('고춧가루', 0.6), ('깐마늘', 0.5)) as v(name, qty)
join items i on i.name = v.name
on conflict (store_id, item_id) do nothing;

-- 대구 북부도매시장 양파·대파 경락가 2주 (가상, source = 'demo' — 실제 API 수집 후 삭제)
insert into wholesale_prices (trade_date, whsl_mrkt_cd, item_id, gds_sclsf_nm, grade_nm,
                              unit_qty, unit_nm, avg_price, low_price, high_price, total_qty, source)
select d::date, '220001', i.id, i.name, '특', 1, 'kg',
       round(v.start_price * (1 + v.daily_change * (d::date - '2026-10-20'::date))),
       round(v.start_price * (1 + v.daily_change * (d::date - '2026-10-20'::date)) * 0.85),
       round(v.start_price * (1 + v.daily_change * (d::date - '2026-10-20'::date)) * 1.15),
       v.volume, 'demo'
from generate_series('2026-10-20'::date, '2026-11-02'::date, interval '1 day') d
cross join (values ('양파', 1050, 0.025, 180000), ('대파', 2400, 0.008, 42000))
           as v(name, start_price, daily_change, volume)
join items i on i.name = v.name
where extract(isodow from d) <> 7                            -- 일요일 휴장
on conflict do nothing;

-- 확인용: 메뉴 원가율
-- select menu_name, price, cost_per_serving, cost_ratio_pct from v_menu_cost_ratio;
