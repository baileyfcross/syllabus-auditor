# Syllabus Auditor 1.0

A self-hosted syllabus compliance checker with official-source monitoring, exact policy validation, fuzzy section detection, optional embedded local Qwen3 inference, PDF/DOCX parsing, OCR, batch audits, correction review, reports, and private accounts. No Ollama integration and no paid AI APIs.

> **Distribution status:** This repository/archive contains the entire application *source* but **does not include the 1.28 GB Qwen3 model or prebuilt runtime binaries**. The provided environment could not retrieve external binary weights. Therefore it is **not yet a complete offline release**. Rule-based checks run without AI. To produce the complete offline package on an internet-connected build computer, use the packaging instructions below. Do not call the source ZIP a self-contained AI installation.

## Requirements

- Python 3.11–3.12 recommended, with pip (3.13 support is dependent on `llama-cpp-python` wheel availability)
- For scanned PDF OCR: Tesseract OCR must be available on the server or host (`apt install tesseract-ocr`, `brew install tesseract`, or Windows Tesseract installer). In Docker it is included.
- 6–8 GB RAM recommended for the bundled Qwen3-1.7B Q4 model; additional memory for multiple document-analysis workers.
- Internet access is **not required at runtime for the AI**. Official online catalog checks naturally require access to approved catalog/policy websites.

## Start locally (source mode)

**Windows (PowerShell):**

```powershell
.\start-local.ps1
```

**macOS / Linux:**

```bash
./start-local.sh
```

Navigate to `http://127.0.0.1:8765`. The first-run setup token is printed to the console, and stored in `data/bootstrap-token.txt` until the first administrator account is created. Use a username and a password of 12+ characters. After setup, sign in.

The launcher installs Python packages at setup, so source mode is not an offline binary installer. It installs the standard Python dependencies; it attempts the embedded `llama-cpp-python` runtime only if the model weights are already present. It never installs Ollama. A missing model or runtime is clearly reported in the UI, and deterministic validation remains available.

## Build a fully offline delivery before deployment

On a computer with internet access, Python 3.12, and the same OS/architecture as the intended recipient:

```bash
python tools/build_distribution.py --complete --output syllabus-auditor-offline.zip
```

The builder downloads the official 1.28GB GGUF at **build time only**, verifies the pinned SHA256, builds platform-specific Python wheels locally, and includes them alongside the application in a ZIP. Run `python tools/install_offline.py` from the extracted full package to install those wheels with `--no-index`. Then use `./run-offline.sh` (macOS/Linux) or `run-offline.bat` (Windows) to start without re-installing dependencies. The offline builder does not bundle an entire Python interpreter, so Python itself must be present on the target machine. Native GUI installers are not provided.

The upstream open-weight model is Apache-2.0. Check all included dependency licenses before redistributing to other institutions. The runtime app has **no model downloader, AI keys, Ollama endpoint, or paid API configuration**.

## Deploy under a subdomain

The application includes a `Dockerfile` and `docker-compose.yml`. **Build only after staging the verified model**:

```bash
python tools/prepare_model.py
docker compose up --build -d
docker compose logs -f syllabus-auditor  # first-run setup token
```

The backend listens on the loopback interface at port 8765. Route `syllabi.baileyfcross.info` through an HTTPS reverse proxy (e.g., Caddy/Nginx/Cloudflare Tunnel) to `http://127.0.0.1:8765` and set `SA_SECURE_COOKIES=true` (already set in Compose). Do not forward port 8765 directly to the internet. The app is **not** a static site and needs a container/VM alongside any static frontend hosting. The `data` directory must remain persistent for database, documents, first-run token, source histories, and backups. Back it up securely.

`docker-compose.yml` includes a Linux read-only app image and a writable data bind mount. Some hosts may require `chmod 777 data` *for diagnosis only*; prefer a restricted ownership mapping to UID 10001 in production (e.g. `sudo chown -R 10001:10001 data && chmod 700 data`). The container's port is bound only to localhost by default. It uses a single Uvicorn worker to keep the in-process job queue coordinated.

## Workflow

1. Create an administrator at first login.
2. Add institution profile, official catalog homepage, and additional approved official hosts.
3. Upload master syllabus template; mark which extracted headings are mandatory.
4. Add required policy statements and set matching mode: exact, semantic, presence or heading. Optionally list approved alternative wordings, department restrictions, source URLs and effective dates.
5. Add course catalog records by course code and academic year; verify them against an official HTTPS URL. The bounded discovery tool can search linked official pages but all candidate text must be approved manually.
6. Upload one or many DOCX/PDF/TXT syllabi, with academic year and optional master template.
7. Inspect findings, original locations, expected vs observed wording, source links and confidence. Approve review actions, export PDF/DOCX reports, and download conservative corrected DOCX copies.
8. Source monitoring periodically checks approved URLs and stages changes instead of silently changing policy or catalog reference text.

### Validation safety

AI selects candidate locations only; it does not make authoritative compliance decisions. Exact approved text checks remain deterministic. Semantic matches below threshold require review. A reference that has never been verified is not silently treated as official. The application retains previous audits and reference revisions.

### Data and security

- Passwords: salted PBKDF2-SHA256 (390,000 iterations); server-side sessions in SQLite and HttpOnly Strict cookies.
- CSRF token required for mutating authenticated endpoints and optional Origin validation.
- Secure HTTPS is required for hosted mode; configure reverse-proxy security independently.
- File uploads are type/size checked, use random storage paths and are only accessible to authenticated users.
- Source fetching only supports HTTPS from approved institution domains and rejects DNS resolutions to non-public IPs; redirects are revalidated. Never configure broad external domains.
- Only configured official websites are fetched. Uploaded documents remain private to the server and are never sent to an external AI provider.
- No connection to Ollama or paid AI APIs; the only outbound traffic is for catalog/policy verification.

### Known technical limitations

- The source distribution lacks the model weights/native AI runtime; embedded AI quality and CPU speed are unverified in this environment.
- Web catalogs behind authentication, bot protection, or JavaScript-only search may require an administrator-provided official URL/document; the crawler cannot bypass access controls.
- Scanned PDFs depend on Tesseract being installed; it may misread difficult scans. These are flagged for review where extraction fails.
- A corrected DOCX is generated only for an exact, unambiguous paragraph match. Complex multi-run/table content may need manual correction; original formatting may change within the replaced paragraph.
- PDF export gives a textual report, not an edited PDF. The UI presents extracted text alongside findings and allows opening the original PDF separately.
- A single shared institution library is visible to authenticated reviewers. This release does not provide tenant-level isolation across independent organizations.
- Revision history records rule/config updates, but templates edited in place do not preserve complete historical document versions. Audit evidence itself is retained.

## Automated tests

```bash
python -m pytest -q
node --check app/static/app.js
```

Tests cover authentication, required policies, matching, uploads, export and source URL validation, but do not validate end-to-end quantized model inference or official website availability.
