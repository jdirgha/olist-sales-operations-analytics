# Business Insights

Findings from the Olist marketplace data (99,441 orders, September 2016 – October 2018).
Every number below comes from the SQL in `sql/` and can be reproduced with `python -m src.pipeline`;
the query that produces each figure is named in brackets.

**Definitions used throughout**
- **Revenue** = item price + freight for orders that were not `canceled` or `unavailable` (gross merchandise value, not Olist's commission or profit).
- **Late** = delivered after the estimated delivery date. Delivery metrics use the 96,282 delivered orders with a delivery date and consistent lifecycle dates.
- **Trend charts** use January 2017 – August 2018. Months before and after are too sparse to compare.

---

## Executive summary

1. **The business more than doubled in a year, driven by order volume, not basket size.** Revenue in January–August 2018 was R$8.59M, up **140.4%** on the same months of 2017. Order count grew 135.1%, while average order value rose only **1.3%**.
2. **Growth has stalled.** Monthly revenue has been flat at about R$1.0–1.16M since March 2018 and slipped **13.8%** from the April 2018 peak to August 2018.
3. **Delivery is reliable on average but breaks down in two places:** peak periods and the North/Northeast. 6.78% of deliveries are late nationally. That rose to **18.96%** for orders placed in March 2018 and reached **21.41%** in Alagoas.
4. **Late deliveries are a carrier problem first.** Late orders spend **27.9 days** in transit against 8.0 days for on-time orders. Sellers also take twice as long to hand them over (5.6 vs 2.6 days).
5. **Seven mid-to-large states hold 28% of revenue but 43% of all late orders** (RJ, SC, BA, ES, PE, CE, PA). They are the highest-value place to improve delivery.
6. **Customers rarely come back.** Only **3.1%** of customers placed more than one order, so revenue depends almost entirely on acquiring new customers.

---

## 1. Sales performance

| KPI | Value | Source query |
|---|---|---|
| Total revenue | R$15,735,527.03 | `total_revenue` |
| of which product value / freight | R$13,494,400.74 / R$2,241,126.29 | `total_revenue` |
| Orders placed | 99,441 | `total_orders` |
| Customers (people) | 96,096 | `total_orders` |
| Average order value | R$160.24 (median R$105.28) | `average_order_value` |
| Cancellation rate | 0.63% (1.24% including unavailable) | `cancellation_rate` |

**Growth came from volume.** Jan–Aug 2018 against Jan–Aug 2017, compared on the same calendar months so seasonality doesn't distort it:

| Metric | Jan–Aug 2017 | Jan–Aug 2018 | Change |
|---|---|---|---|
| Revenue | R$3,574,992 | R$8,593,138 | +140.4% |
| Orders placed (all statuses) | 22,968 | 53,991 | +135.1% |
| Average order value | R$158.45 | R$160.53 | +1.3% |

**Black Friday is the single biggest event.** November 2017 revenue was R$1,172,192, up 53.3% on October (`monthly_revenue_mom`). On 24 November 2017 alone, 1,176 orders brought in R$178,378. That is 2.5× the next-best day.

**The plateau.** Revenue peaked at R$1,156,249 in April 2018 and has drifted down since, reaching R$996,974 in August (−13.8%). Without a return to growth, 2018's second half will look like its first.

**Revenue is concentrated** (`top_10_categories`, `revenue_by_state`):
- The top 10 of 74 categories (73 named, plus `unknown`) generate **62.3%** of revenue. They are led by health_beauty (R$1.44M), watches_gifts (R$1.30M) and bed_bath_table (R$1.24M).
- São Paulo alone is **37.4%** of revenue, and SP, RJ and MG together are **62.5%**.

**Category momentum** (`category_trend_recent_vs_prior`, Mar–Aug 2018 against Sep 2017–Feb 2018, categories with at least 50 orders):
- Growing: musical_instruments (+27.9%), small_appliances (+23.0%), office_furniture (+18.4%), furniture_decor (+17.8%), electronics (+17.7%).
- Shrinking: computers (−55.1%), toys (−38.8%), cool_stuff (−34.5%), consoles_games (−28.1%).
- **Caveat:** the earlier window contains Black Friday and Christmas, so declines in gift-type categories (toys, cool_stuff, consoles) are at least partly seasonal. A same-season comparison needs data beyond October 2018. The decline in computers (−55%) is too large to explain by seasonality alone and is worth investigating.

**Freight is a meaningful cost to customers.** It averages R$22.82 per order and **16.6%** of product value (`average_freight_cost`). The burden grows with distance: R$41.39 per order (18.5% of revenue) in the North against R$19.86 (13.2%) in the Southeast.

---

## 2. Operational performance

| KPI | Value | Source query |
|---|---|---|
| Delivered orders measured | 96,282 | `delivery_time_summary` |
| Average / median delivery time | 12.57 / 10.23 days | `delivery_time_summary` |
| 90th percentile delivery time | 23.11 days | `delivery_time_summary` |
| Average promised (estimated) time | 23.74 days | `estimated_vs_actual_delivery` |
| Late delivery rate | 6.78% (6,532 orders) | `late_delivery_rate` |
| Average delay when late | 10.62 days | `estimated_vs_actual_delivery` |

**Estimates are very conservative.** 91.9% of orders arrive before the estimated date, on average 11.2 days early (`delivery_timeliness_distribution`). Customers are told to expect roughly twice the actual delivery time.

**Late deliveries cluster in time** (`late_deliveries_by_month`):

| Purchase month | Late % | Delivered orders |
|---|---|---|
| Oct 2017 | 4.18% | 4,478 |
| **Nov 2017** (Black Friday) | **12.40%** | 7,288 |
| Jan 2018 | 5.70% | 7,069 |
| **Feb 2018** | **14.13%** | 6,555 |
| **Mar 2018** | **18.96%** | 7,003 |
| Jun 2018 | 1.16% | 6,050 |

The November spike follows a 63% jump in delivered orders on October. February–March 2018 had no comparable volume jump, and the dataset doesn't contain the cause (for example carrier capacity, weather or strikes). It should be investigated with the logistics team.

**Where the time is lost** (`fulfilment_stage_times`):

| Stage | Late orders | On-time orders |
|---|---|---|
| Payment approval | 0.51 days | 0.42 days |
| Seller hand-off to carrier | 5.55 days | 2.60 days |
| Carrier transit | **27.89 days** | 7.98 days |

Carrier transit explains most of the gap. Slow seller hand-off is a secondary but real contributor.

**Late orders are also more expensive to ship:** freight averages R$25.25 against R$22.60 for on-time orders (`freight_cost_summary`). That is consistent with longer, more remote routes.

**Revenue exposed to late delivery:** R$1,150,711 (7.5% of delivered-order revenue) came from orders that arrived late.

---

## 3. Regional performance

**Late rates by state** (`late_deliveries_by_state`) are highest in the Northeast: AL 21.41%, MA 17.51%, SE 15.27%, PI 13.95%, CE 13.77%. Among the largest markets, **RJ is the outlier at 12.12%** (1,495 late orders, 22.9% of all late deliveries nationally). SP sits at 4.50% with the fastest delivery in the country (8.77 days).

**Macro-regions** (`macro_region_performance`):

| Region | Revenue share | Avg order value | Late % | Avg delivery days |
|---|---|---|---|---|
| Southeast | 64.6% | R$150.88 | 6.12% | 10.76 |
| South | 14.5% | R$162.87 | 5.92% | 14.05 |
| Northeast | 11.9% | R$201.24 | **12.72%** | 20.01 |
| Center-West | 6.4% | R$176.98 | 6.54% | 15.04 |
| North | 2.6% | R$223.41 | 8.58% | 22.61 |

Customers in the North and Northeast spend **33–48% more per order** than in the Southeast, and they get the slowest, least reliable delivery.

**Segments** (`segment_summary`). States are split by revenue (at or above the median state, R$186,005) and by whether their late rate is above the national 6.78%:

| Segment | States | Revenue share | Share of all late orders | Late % |
|---|---|---|---|---|
| Higher revenue, late rate at or below national | SP, MG, RS, PR, DF, GO, MT | 65.3% | 48.4% | 4.72% |
| **Higher revenue, late rate above national** | **RJ, SC, BA, ES, PE, CE, PA** | **28.4%** | **43.3%** | **11.36%** |
| Lower revenue, late rate above national | MA, PB, MS, PI, RN, AL, SE, TO, RR | 5.6% | 8.0% | 13.39% |
| Lower revenue, late rate at or below national | RO, AM, AC, AP | 0.8% | 0.2% | 2.99% |

RR, AP and AC have fewer than 100 delivered orders, so their rates are flagged `small_sample`.

---

## 4. Customers

- 96,096 people placed 99,441 orders. Only **2,997 (3.1%)** ordered more than once.
- Combined with flat revenue since March 2018, this means growth depends on continuously acquiring new customers.

---

## 5. Recommendations

These follow from the findings above. Items marked *hypothesis* need a test before acting on them.

1. **Target carrier performance in the 7 "higher revenue, late rate above national" states**, starting with RJ. They concentrate 43% of late orders on 28% of revenue, and RJ alone accounts for 23% of national late deliveries. Track late % by state and carrier monthly.
2. **Plan peak capacity before Black Friday.** Late rates tripled in November 2017. Agree carrier capacity and seller dispatch targets in advance, and investigate the Feb–Mar 2018 spike so it isn't repeated.
3. **Introduce a seller hand-off target**, for example dispatch within 3 days. Late orders wait 5.6 days before reaching the carrier against 2.6 days for on-time orders.
4. **Review delivery estimates** *(hypothesis)*. Orders arrive 11 days early on average. Tighter, still-reliable estimates could improve checkout conversion, especially in the Southeast where delivery is fastest. This should be A/B tested, because tighter estimates would also raise the late rate.
5. **Invest in retention.** With a 3.1% repeat rate, even a small increase in second orders would offset the revenue plateau. Post-delivery offers to customers whose orders arrived on time are a natural starting point.
6. **Watch the computers category**, which fell 55% between the two half-years. Re-check all category trends year over year once later data is available.

---

## 6. Limitations

- **Coverage:** orders run from September 2016 to October 2018. 2016 and September–October 2018 are sparse, which is why trends use January 2017 – August 2018. The most recent months may slightly understate delivery time, because orders still in transit aren't measured yet. In August 2018, 161 of 6,512 orders (2.5%) were not delivered when the data was extracted.
- **Revenue ≠ profit:** the dataset has no product cost, commission or shipping cost data, so profitability can't be analysed.
- **Region = customer delivery address.** Seller locations, reviews and geolocation are available in the source but are outside this project's scope.
- **Causation:** the analysis shows *where* and *when* delays happen, not *why*. Carrier identity is not in the data.
- **Data quality:** 189 orders with impossible date sequences are kept for revenue but excluded from delivery-time metrics. Full details are in [`data_quality_report.md`](data_quality_report.md).
