"""Standard line items mapped to candidate XBRL tags, in priority order.

For each line item the builder uses the tag with the most recent data (ties go to
the earlier tag in the list), then fills older gaps from the remaining tags.
"""

# Flow items (income statement / cash flow), duration facts
FLOW = {
    "revenue": {
        "us-gaap": [
            "RevenuesNetOfInterestExpense",
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "SalesRevenueServicesNet",
        ],
        "ifrs-full": ["Revenue", "RevenueFromContractsWithCustomers"],
    },
    "cost_of_revenue": {
        "us-gaap": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
        "ifrs-full": ["CostOfSales"],
    },
    "gross_profit": {"us-gaap": ["GrossProfit"], "ifrs-full": ["GrossProfit"]},
    "rnd": {
        "us-gaap": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
        "ifrs-full": ["ResearchAndDevelopmentExpense"],
    },
    "sga": {
        "us-gaap": ["SellingGeneralAndAdministrativeExpense"],
        "ifrs-full": ["SellingGeneralAndAdministrativeExpense"],
    },
    "selling_marketing": {
        "us-gaap": ["SellingAndMarketingExpense", "MarketingAndAdvertisingExpense"],
        "ifrs-full": ["SellingExpense", "DistributionCosts"],
    },
    "g_and_a": {
        "us-gaap": ["GeneralAndAdministrativeExpense"],
        "ifrs-full": ["AdministrativeExpense", "GeneralAndAdministrativeExpense"],
    },
    "operating_income": {
        "us-gaap": ["OperatingIncomeLoss"],
        "ifrs-full": ["ProfitLossFromOperatingActivities"],
    },
    "interest_expense": {
        "us-gaap": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
        "ifrs-full": ["FinanceCosts", "InterestExpense"],
    },
    "pretax_income": {
        "us-gaap": [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ],
        "ifrs-full": ["ProfitLossBeforeTax"],
    },
    "income_tax": {
        "us-gaap": ["IncomeTaxExpenseBenefit"],
        "ifrs-full": ["IncomeTaxExpenseContinuingOperations"],
    },
    "net_income": {
        "us-gaap": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
        "ifrs-full": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    },
    "eps_basic": {
        "us-gaap": ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"],
        "ifrs-full": ["BasicEarningsLossPerShare"],
    },
    "eps_diluted": {
        "us-gaap": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
        "ifrs-full": ["DilutedEarningsLossPerShare"],
    },
    "shares_diluted": {
        "us-gaap": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
        "ifrs-full": ["WeightedAverageShares", "AdjustedWeightedAverageShares"],
    },
    "d_and_a": {
        "us-gaap": [
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
            "Depreciation",
        ],
        "ifrs-full": [
            "DepreciationAndAmortisationExpense",
            "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
        ],
    },
    "depreciation": {
        "us-gaap": ["Depreciation", "DepreciationNonproduction"],
        "ifrs-full": ["DepreciationExpense", "DepreciationPropertyPlantAndEquipment"],
    },
    "amortization": {
        "us-gaap": ["AmortizationOfIntangibleAssets"],
        "ifrs-full": ["AmortisationExpense", "AmortisationIntangibleAssetsOtherThanGoodwill"],
    },
    "sbc": {
        "us-gaap": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
        "ifrs-full": ["ExpenseFromSharebasedPaymentTransactionsWithEmployees"],
    },
    "cfo": {
        "us-gaap": [
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
        "ifrs-full": ["CashFlowsFromUsedInOperatingActivities"],
    },
    "capex": {
        "us-gaap": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "PaymentsForCapitalImprovements",
        ],
        "ifrs-full": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    },
    "dividends_paid": {
        "us-gaap": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
        "ifrs-full": ["DividendsPaidClassifiedAsFinancingActivities"],
    },
    "buybacks": {
        "us-gaap": ["PaymentsForRepurchaseOfCommonStock"],
        "ifrs-full": ["PaymentsToAcquireOrRedeemEntitysShares"],
    },
}

# Balance sheet items, instant facts
INSTANT = {
    "cash": {
        "us-gaap": [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "Cash",
        ],
        "ifrs-full": ["CashAndCashEquivalents"],
    },
    "st_investments": {
        "us-gaap": ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
        "ifrs-full": ["CurrentFinancialAssetsAtAmortisedCost", "OtherCurrentFinancialAssets"],
    },
    "receivables": {"us-gaap": ["AccountsReceivableNetCurrent"], "ifrs-full": ["TradeAndOtherCurrentReceivables"]},
    "inventory": {"us-gaap": ["InventoryNet"], "ifrs-full": ["Inventories"]},
    "current_assets": {"us-gaap": ["AssetsCurrent"], "ifrs-full": ["CurrentAssets"]},
    "goodwill": {"us-gaap": ["Goodwill"], "ifrs-full": ["Goodwill"]},
    "total_assets": {"us-gaap": ["Assets"], "ifrs-full": ["Assets"]},
    "current_liabilities": {"us-gaap": ["LiabilitiesCurrent"], "ifrs-full": ["CurrentLiabilities"]},
    "total_liabilities": {"us-gaap": ["Liabilities"], "ifrs-full": ["Liabilities"]},
    "total_equity": {
        "us-gaap": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "ifrs-full": ["EquityAttributableToOwnersOfParent", "Equity"],
    },
    # Debt pieces: total_debt is derived (see financials.derive)
    "debt_lt_total": {"us-gaap": ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount"], "ifrs-full": []},
    "debt_noncurrent": {
        "us-gaap": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermNotesPayable"],
        "ifrs-full": ["NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings", "NoncurrentBondsIssued"],
    },
    "debt_current": {
        "us-gaap": ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
        "ifrs-full": ["CurrentPortionOfLongtermBorrowings", "CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued"],
    },
    "short_borrowings": {
        "us-gaap": ["ShortTermBorrowings", "CommercialPaper"],
        "ifrs-full": ["ShorttermBorrowings"],
    },
}

# Items that are per-share or share counts (not summed or scaled like currency)
PER_SHARE = {"eps_basic", "eps_diluted"}
SHARE_COUNT = {"shares_diluted"}
