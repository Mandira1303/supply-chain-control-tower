# Project 2: Supply Chain & Sales Dashboard (Power BI + SQL Server)

An executive sales dashboard built on the **AdventureWorksDW2022** data warehouse. It uses a clean star schema, DAX time-intelligence measures, drill-through, row-level security by region, and an automated SQL refresh job. The report is published to Power BI Service.

**Author:** Mandira Biswas | **Track:** Data Analytics | **Submission date:** 20 Nov 2026

---

## 1. Tech Stack
| Layer | Tool |
|---|---|
| Database | SQL Server 2025 (Evaluation) + SSMS 22 |
| Data source | AdventureWorksDW2022 |
| ETL / cleaning | Power Query (Power BI Desktop) |
| Modelling & measures | Power BI data model + DAX |
| Scheduling | SQL Server Agent job (daily, 02:00) |
| Delivery | Power BI Service (My workspace) |

## 2. Architecture
```
AdventureWorksDW2022 (SQL Server)
        |
        |  SQL Agent job: Refresh Sales Summary (daily 02:00)
        |  -> EXEC dbo.usp_RefreshSalesSummary  (rebuilds dbo.SalesSummary)
        v
Power BI Desktop (Power Query -> Star schema -> DAX)
        |
        |  Publish
        v
Power BI Service (report + semantic model + RLS roles)
```
> Add your architecture diagram image here: `docs/architecture.png`

## 3. Data Model (Star Schema)
**Fact table:** `Sales` (from FactInternetSales)

**Dimensions:** `Date`, `Product` (with Subcategory and Category), `Customer`, `Territory`

| Relationship | Type |
|---|---|
| Sales[OrderDateKey] -> Date[DateKey] | Active |
| Sales[DueDateKey] -> Date[DateKey] | Inactive |
| Sales[ProductKey] -> Product[ProductKey] | Active |
| Sales[SalesTerritoryKey] -> Territory[SalesTerritoryKey] | Active |
| Sales[CustomerKey] -> Customer[CustomerKey] | Active |

The `Date` table is marked as the date table. Order date is the active relationship, so the time-intelligence measures use it.

> Add a Model view screenshot here: `docs/model_view.png`

## 4. DAX Measures
```DAX
Total Sales = SUM(Sales[SalesAmount])
Total Cost  = SUM(Sales[TotalProductCost])
Profit      = [Total Sales] - [Total Cost]
Margin %    = DIVIDE([Profit], [Total Sales])

Sales YTD = IF(NOT ISBLANK([Total Sales]),
    TOTALYTD([Total Sales], 'Date'[FullDateAlternateKey]))

Sales Prior Year = CALCULATE([Total Sales],
    SAMEPERIODLASTYEAR('Date'[FullDateAlternateKey]))

YoY Growth % = IF(NOT ISBLANK([Total Sales]),
    DIVIDE([Total Sales] - [Sales Prior Year], [Sales Prior Year]))

Sales Rolling 3M = IF(NOT ISBLANK([Total Sales]),
    CALCULATE([Total Sales],
        DATESINPERIOD('Date'[FullDateAlternateKey],
            MAX('Date'[FullDateAlternateKey]), -3, MONTH)))
```

## 5. Report Pages
1. **Executive Summary:** KPI cards (Total Sales, Profit, Margin %), monthly sales trend, sales by product category, sales by territory, and a CalendarYear slicer.
2. **Product Details (drill-through):** a product-level table with Total Sales, Profit, and Margin %. Right-click a product on the Executive page and choose Drill through.

## 6. Row-Level Security
Roles are defined on the `Territory` table (Modeling -> Manage roles):

| Role | DAX filter |
|---|---|
| North America | `[SalesTerritoryGroup] = "North America"` |
| Europe | `[SalesTerritoryGroup] = "Europe"` |
| Pacific | `[SalesTerritoryGroup] = "Pacific"` |

Tested in Desktop with **Modeling -> View as**. Roles are visible in Power BI Service under the semantic model's **Security** setting.

## 7. Automated Refresh
A stored procedure rebuilds a summary table, and a SQL Server Agent job runs it daily.

```sql
CREATE OR ALTER PROCEDURE dbo.usp_RefreshSalesSummary AS
BEGIN
  IF OBJECT_ID('dbo.SalesSummary') IS NOT NULL DROP TABLE dbo.SalesSummary;
  SELECT d.CalendarYear, d.EnglishMonthName, t.SalesTerritoryRegion,
         SUM(f.SalesAmount) AS TotalSales, SUM(f.TotalProductCost) AS TotalCost
  INTO dbo.SalesSummary
  FROM dbo.FactInternetSales f
  JOIN dbo.DimDate d ON f.OrderDateKey = d.DateKey
  JOIN dbo.DimSalesTerritory t ON f.SalesTerritoryKey = t.SalesTerritoryKey
  GROUP BY d.CalendarYear, d.EnglishMonthName, t.SalesTerritoryRegion;
END;
```
- **Job:** `Refresh Sales Summary` (step: `EXEC dbo.usp_RefreshSalesSummary;`)
- **Schedule:** Daily at 02:00. Last run: Success.
- **Note:** Scheduled refresh in Power BI Service for a local SQL Server needs an on-premises data gateway. This project does not use one. Data is refreshed with **Home -> Refresh** in Desktop and then republished.

## 8. Setup Instructions
1. Install SQL Server (Evaluation), SSMS, and Power BI Desktop.
2. Restore `AdventureWorksDW2022.bak` in SSMS (Databases -> Restore Database -> Device).
3. Run the stored procedure script in section 7 on `AdventureWorksDW2022`.
4. Enable Agent XPs, then create the job:
   ```sql
   EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
   EXEC sp_configure 'Agent XPs', 1; RECONFIGURE;
   ```
5. Open `Supply_Chain_Sales_Dashboard.pbix`. If asked, change the data source to your server name (Home -> Transform data -> Data source settings), and untick **Use encrypted connection** for a local server.
6. Click **Refresh**, then **Publish** to your workspace.

## 9. Testing
| Test | Expected | Result |
|---|---|---|
| Total Sales card | About $29M (all years, all regions) | Pass |
| Margin % | Profit / Sales = 41.15% | Pass |
| Year slicer filters all visuals | Visuals change | Pass |
| Drill-through from product | Opens Product Details for that product | Pass |
| RLS "Europe" view | Only European territories shown | Pass |
| SQL Agent job run | Succeeded | Pass |
| Published report opens in Service | Both pages load | Pass |

## 10. Repository Contents
```
README.md
Supply_Chain_Sales_Dashboard.pbix
sql/usp_RefreshSalesSummary.sql
docs/architecture.png
docs/model_view.png
docs/screenshots/
docs/User_Guide.md
```

## 11. Limitations & Future Work
- Scheduled cloud refresh needs a gateway (not set up).
- Add a Customer Details drill-through page.
- Add a measure for Days to Ship (from OrderDate and ShipDate).
