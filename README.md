# Prompt Injection Firewall

A multi-layer AI security system designed to detect prompt injection, jailbreak attempts, and unsafe privileged actions in conversational agents.

## Overview

This project implements a layered defense pipeline:

1. Layer 1: Regex + ChromaDB vector similarity prefilter
2. Layer 2: XGBoost feature-based classifier
3. Layer 3: DistilBERT deep classifier for borderline cases
4. Layer 4: Pydantic policy validator for business-rule enforcement

## Project structure

```text
.
├── api/
│   ├── main.py
│   ├── schemas.py
│   └── routes/
├── data/
│   ├── raw/
│   ├── processed/
│   ├── scripts/
│   └── chroma_db/
├── docs/
├── evaluation/
├── firewall/
├── frontend/
├── models/
│   ├── layer1_prefilter/
│   ├── layer2_xgboost/
│   └── layer3_distilbert/
├── tests/
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
├── README.md
├── requirements.txt
└── ai_firewall_agent_roadmap.md
```

## Clone and run locally

### 1. Clone the repo

```bash
git clone https://github.com/giatin110406-pixel/PromptInjectionFirewall.git
cd PromptInjectionFirewall
```

### 2. Create and activate virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the data pipeline

Download the public dataset and build the processed datasets:

```bash
python data/scripts/download_datasets.py
python data/scripts/prepare_real_datasets.py
```

If you want to try the optional indirect prompt injection source:

```bash
python data/scripts/prepare_real_datasets.py --include-bipia
```

### 5. Build Layer 2 feature set and train the model

```bash
python models/layer2_xgboost/build_feature_dataset.py
python models/layer2_xgboost/train.py
```

### 6. Train Layer 3 DistilBERT

```bash
python models/layer3_distilbert/train.py
```

### 7. Run the API

```bash
python -m uvicorn api.main:app --reload
```

Open the API docs in browser:

```text
http://127.0.0.1:8000/docs
```

### 8. Run tests

```bash
pytest
```

## Notes

- The project is designed for prompt injection and jailbreak detection in LLM-based conversational systems.
- Layer 1 uses a jailbreak pattern database and ChromaDB vector similarity.
- Layer 2 uses engineered features with XGBoost.
- Layer 3 uses a fine-tuned DistilBERT classifier for borderline or ambiguous prompts.
- Layer 4 validates business actions with Pydantic.

## Security note

Do not commit secrets, API keys, tokens, credentials, or local environment files. Keep them in a local .env file or a secret manager.

Example:

```bash
copy NUL .env
```

Then add the secret variables there, and ensure .env is excluded from Git by .gitignore.

---

# Phiên bản tiếng Việt

# Prompt Injection Firewall

Dự án này là hệ thống bảo vệ AI đa lớp, được thiết kế để phát hiện prompt injection, jailbreak và các hành vi vượt quyền hoặc thao tác không an toàn trong agent hội thoại.

## Tổng quan

Project triển khai một pipeline phòng thủ theo nhiều tầng:

1. Layer 1: Regex + ChromaDB vector similarity prefilter
2. Layer 2: XGBoost feature-based classifier
3. Layer 3: DistilBERT deep classifier cho trường hợp mơ hồ
4. Layer 4: Pydantic policy validator để kiểm tra logic nghiệp vụ

## Cấu trúc dự án

```text
.
├── api/
│   ├── main.py
│   ├── schemas.py
│   └── routes/
├── data/
│   ├── raw/
│   ├── processed/
│   ├── scripts/
│   └── chroma_db/
├── docs/
├── evaluation/
├── firewall/
├── frontend/
├── models/
│   ├── layer1_prefilter/
│   ├── layer2_xgboost/
│   └── layer3_distilbert/
├── tests/
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
├── README.md
├── requirements.txt
├── ai_firewall_agent_roadmap.md
└── push_to_github.sh
```

## Cách clone và chạy trên máy local

### 1. Clone repo

```bash
git clone https://github.com/giatin110406-pixel/PromptInjectionFirewall.git
cd PromptInjectionFirewall
```

### 2. Tạo và kích hoạt môi trường ảo

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 4. Chạy pipeline dữ liệu

Tải dataset public và build các file xử lý:

```bash
python data/scripts/download_datasets.py
python data/scripts/prepare_real_datasets.py
```

Nếu muốn thử thêm nguồn dữ liệu public khác dạng indirect prompt injection:

```bash
python data/scripts/prepare_real_datasets.py --include-bipia
```

### 5. Build feature set cho Layer 2 và train model

```bash
python models/layer2_xgboost/build_feature_dataset.py
python models/layer2_xgboost/train.py
```

### 6. Train Layer 3 DistilBERT

```bash
python models/layer3_distilbert/train.py
```

### 7. Chạy API

```bash
python -m uvicorn api.main:app --reload
```

Sau đó mở:

```text
http://127.0.0.1:8000/docs
```

### 8. Chạy test

```bash
pytest
```

## Giải thích từng layer

- Layer 1: lọc nhanh bằng regex + vector similarity trên ChromaDB
- Layer 2: phân loại dựa trên feature engineering bằng XGBoost
- Layer 3: mô hình sâu DistilBERT cho những prompt mơ hồ hoặc borderline
- Layer 4: kiểm tra policy action bằng Pydantic để chặn hành vi vi phạm quy tắc nghiệp vụ

## Lưu ý về dữ liệu

Dự án hướng đến dữ liệu prompt injection/public thật và không sử dụng dữ liệu giả làm nguồn dữ liệu chính. Nếu bạn muốn thêm dataset public khác, hãy kiểm tra kỹ nguồn gốc và độ tin cậy trước khi đưa vào pipeline.

## Lưu ý về bảo mật

Không commit secret, API key, token, credential hoặc file môi trường local. Tất cả secret nên được lưu trong file .env hoặc quản lý qua secret manager.

Ví dụ:

```bash
copy NUL .env
```

Sau đó thêm biến môi trường vào file đó và đảm bảo .env được loại trừ khỏi Git bằng .gitignore.

## Tài liệu tham khảo

- [ai_firewall_agent_roadmap.md](ai_firewall_agent_roadmap.md)
- [docs/](docs)
- [evaluation/](evaluation)

