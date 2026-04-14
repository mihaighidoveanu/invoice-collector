# invoice-collector

A FastAPI service that collects monthly invoices from Gmail using a bank statement as the source of truth. Given a bank statement PDF, the agent identifies all vendors and amounts for the target month, generates Gmail search rules per vendor, searches Gmail for matching invoices, downloads and saves them locally, and produces an Excel report for the accountant.

