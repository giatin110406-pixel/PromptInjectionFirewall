# Data Audit Report: Threat Detection Dataset

## 1. Dataset Overview
- **Location**: `data/processed/ground_truth.csv`
- **Total Clean Samples**: 738 records
- **Feature Set**: `data/processed/features.csv` (25 extracted numeric features)

## 2. Taxonomy & Label Distribution
| Label | Count | Percentage | Description |
|---|---|---|---|
| `INJECTION_PROMPT` | 255 | 34.55% | Direct jailbreaks, DAN persona, system prompt extraction |
| `PRIVILEGE_ESCALATION` | 232 | 31.44% | Authority claims (admin, auditor, emergency responder overrides) |
| `SAFE` | 191 | 25.88% | Benign customer support queries, product issues, technical Q&A |
| `INJECTION_PAYLOAD` | 60 | 8.13% | SQL injections, template injections, command execution scripts |
| **Total** | **738** | **100.0%** | |

## 3. Binary Label Breakdown
- **Malicious (1)**: 547 samples (74.12%)
- **Safe (0)**: 191 samples (25.88%)

## 4. Data Quality & Preprocessing
- **Deduplication**: Strict deduplication on normalized text strips identical prompts.
- **Null / Missing Value Audit**: Verified 0 NaN/null values across all text fields and 25 feature columns.
- **Fairness & Bias**: Balanced representation of normal refund queries alongside malicious refund escalation attempts to prevent model bias against standard customer service transactions.
