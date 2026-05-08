#!/usr/bin/env bash
# =============================================================================
# scripts/verify_ocr_bake.sh — Phase 7 OCR-02 acceptance #3 verifier
#
# Confirms that a built rag-enterprise image has PP-StructureV3 model weights
# baked into /home/raguser/.paddlex/official_models — i.e. that the runtime
# image needs NO network access to do OCR.
#
# Usage:
#   bash scripts/verify_ocr_bake.sh                    # default: rag-enterprise:latest
#   bash scripts/verify_ocr_bake.sh rag-enterprise:phase7-test
#
# Exits non-zero on any check failure.
#
# Performs four checks:
#   1. Model directory exists and contains >= 3 sub-dirs (PP-StructureV3 ships
#      layout + table + det + rec — at least 3 dirs).
#   2. PPStructureV3 instantiation under network-disabled run prints "OK".
#   3. Verify the directory is owned by raguser (uid 1001) so the non-root
#      runtime can read it.
#   4. Print final image size for the SUMMARY image-size-delta record.
# =============================================================================
set -euo pipefail

IMAGE="${1:-rag-enterprise:latest}"
MODEL_PATH="/home/raguser/.paddlex/official_models"
MIN_DIRS=3
INSTANTIATE_TIMEOUT=30

echo "[verify_ocr_bake] image=${IMAGE}"
echo "[verify_ocr_bake] model_path=${MODEL_PATH}"

# ── Check 1: model directory exists with >=3 sub-directories ─────────────────
echo
echo "[1/4] checking ${MODEL_PATH} contains >= ${MIN_DIRS} model directories…"
DIR_COUNT=$(docker run --rm --entrypoint sh "${IMAGE}" -c \
    "ls -1 ${MODEL_PATH} 2>/dev/null | wc -l")
if [ "${DIR_COUNT}" -lt "${MIN_DIRS}" ]; then
    echo "FAIL: expected >= ${MIN_DIRS} model dirs under ${MODEL_PATH}, found ${DIR_COUNT}"
    exit 1
fi
echo "  ok — found ${DIR_COUNT} directories"

# ── Check 2: PPStructureV3() instantiation under --network=none ──────────────
echo
echo "[2/4] instantiating PPStructureV3 with --network=none (proves models are baked)…"
if ! timeout "${INSTANTIATE_TIMEOUT}" docker run --rm --network=none --entrypoint python "${IMAGE}" \
        -c "from paddleocr import PPStructureV3; PPStructureV3(use_doc_orientation_classify=False, use_doc_unwarping=False, lang='ch'); print('OK')" \
        | grep -q '^OK$'; then
    echo "FAIL: PPStructureV3 could not load offline; models not baked correctly"
    exit 1
fi
echo "  ok — offline instantiation succeeded"

# ── Check 3: ownership matches raguser ───────────────────────────────────────
echo
echo "[3/4] verifying ${MODEL_PATH} is owned by raguser (uid 1001)…"
OWNER=$(docker run --rm --entrypoint sh "${IMAGE}" -c \
    "stat -c '%U:%u' ${MODEL_PATH}")
if [ "${OWNER}" != "raguser:1001" ]; then
    echo "FAIL: expected raguser:1001, got ${OWNER}"
    exit 1
fi
echo "  ok — owner=${OWNER}"

# ── Check 4: print image size for SUMMARY (image-size delta record) ──────────
echo
echo "[4/4] image size:"
docker images "${IMAGE}" --format "  {{.Repository}}:{{.Tag}} {{.Size}}"

echo
echo "[verify_ocr_bake] all checks passed ✔"
