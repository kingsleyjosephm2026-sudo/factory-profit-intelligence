# Factory Profit Intelligence (FPI)
### Turning Manufacturing Data into Profit Intelligence

**Factory Profit Intelligence (FPI)** is a full-stack manufacturing analytics platform designed to help industrial teams identify profit leakage, investigate operational inefficiencies, prioritize corrective actions, and measure the financial impact of improvement initiatives.

Built around the principle that *every operational loss should be measurable, every recommendation should have evidence, and every claimed saving should be verifiable*, FPI brings production, downtime, quality, energy, and inventory analytics into one unified platform.

> **Engineering prototype:** The current application uses reproducible simulated data for a fictional manufacturer. It is designed for local evaluation and future real-world validation. No real factory deployment, customer result, or financial saving is claimed.

## The Vision

Manufacturers generate enormous amounts of operational data, but identifying where that data translates into financial loss is challenging. FPI aims to bridge that gap by connecting operational metrics with transparent financial calculations and actionable improvement opportunities.

The platform is designed to answer five critical business questions:

- **Where is money being lost?** Identify and rank potential loss sources across factory operations.
- **What is driving operational inefficiency?** Explore patterns in machine downtime, production performance, quality defects, and energy usage.
- **Which actions deserve priority?** Generate evidence-backed recommendations based on deterministic analytical rules.
- **What could improvement be worth?** Estimate avoidable costs and potential savings without treating every loss as recoverable profit.
- **Which savings have actually been verified?** Separate identified opportunities, forecasts, estimates, and verified outcomes.

## Core Capabilities

### 1. Executive Manufacturing Intelligence
A unified overview of production output, defect rates, machine downtime, energy costs, estimated losses, and target attainment, supported by cross-page filters and period comparisons.

### 2. Profit Leakage Analysis
A structured loss-analysis engine that distinguishes observed costs, estimated avoidable costs, and potential savings, with explicit assumptions to reduce double-counting.

### 3. Operational Root-Cause Exploration
Analytical comparisons, correlations, and outlier detection across production lines, machines, products, and shifts. Relationships are presented as associations rather than proof of causation.

### 4. Evidence-Based Recommendation Engine
A deterministic rules engine that generates improvement recommendations with supporting evidence, severity, status tracking, and persistent notes—without requiring a paid AI API.

### 5. Savings Verification Framework
A dedicated workflow for distinguishing identified opportunities, forecast savings, estimated savings, and verified savings. Verification is governed by server-side checks rather than a manually entered positive amount alone.

### 6. Live Manufacturing Simulation
A controllable simulator that generates new demonstration events and writes them into the application's database, allowing users to explore changing metrics, pause or step through activity, and reset the demo.

### 7. Data Ingestion and Quality Controls
CSV validation, duplicate detection, rejected-row reporting, import history, and export functionality designed to make data quality visible before records enter analytical workflows.

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Tailwind CSS, Recharts |
| Backend | Python, FastAPI |
| Data processing | Pandas, NumPy |
| Database | PostgreSQL, SQLite development fallback |
| Data access and migrations | SQLAlchemy, Alembic |
| Testing | pytest, frontend tests, TypeScript checks |
| Development and deployment | Docker Compose configuration |
| Data exchange | CSV import and export |

## Engineering Highlights

- **12 application pages** covering executive reporting, production, downtime, quality, energy, inventory, recommendations, savings verification, and data exploration.
- **48 reported API endpoints** supporting analytics, data management, and interactive workflows.
- **13 reported database tables** with migration support.
- **Reproducible 90-day demonstration dataset** covering 10 machines, 3 production lines, and 8 products.
- **98 reported backend tests and 9 reported frontend tests passing** in the original development environment.
- **Interactive workflow testing** reported for filters, simulation controls, recommendation persistence, savings initiatives, and CSV validation.

These figures describe the reported prototype implementation and test results, not independent certification or production validation.

## Responsible Analytics by Design

FPI is designed around transparency rather than inflated business claims:

- Demonstration records are labelled as simulated data.
- Financial estimates depend on documented assumptions.
- Operational correlations are not automatically interpreted as causation.
- Potential savings are not presented as realized profit.
- Verification requires server-side checks.
- Limitations and deployment constraints are documented.

The current loss model includes illustrative assumptions for downtime losses, scrap salvage, and savings realization. These parameters must be validated against authorized company data before the estimates can support operational or financial decisions.

## Getting Started

### Option A — Docker with PostgreSQL

```bash
cp .env.example .env
# Configure POSTGRES_PASSWORD
docker compose up --build
```

Application: `http://localhost:8080`

API documentation: `http://localhost:8000/docs`

*The Docker/PostgreSQL setup has not yet been executed in the reported build environment.*

### Option B — Local Development

**Prerequisites:** Python 3.12+ and Node.js 20+.

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment, then run:

```bash
pip install -r requirements-dev.txt
python -m app.cli init-db
python -m app.cli seed
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` to access the frontend.

See the project documentation for database configuration, migrations, testing, troubleshooting, and deployment details.

## Project Status and Roadmap

FPI is a locally runnable prototype intended to establish the foundation for a more rigorous manufacturing intelligence system.

The next development priorities are:

1. Validate financial calculations against representative, authorized manufacturing data.
2. Execute and verify the complete PostgreSQL deployment.
3. Introduce authentication, role-based access control, and audit logging.
4. Expand reference-data management and data-quality workflows.
5. Conduct a controlled pilot with an industrial partner.
6. Compare predicted opportunities with measured operational outcomes and independently verified savings.

## Long-Term Objective

The long-term objective is to evolve FPI from an analytics prototype into a reliable decision-support platform that helps manufacturers connect operational performance with financial outcomes.

**The guiding principle is simple: identify the loss, explain the evidence, prioritize the intervention, and verify the result.**

---

*Factory Profit Intelligence — a manufacturing analytics engineering project focused on transparent loss analysis, actionable recommendations, and measurable operational improvement.*
