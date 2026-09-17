#!/bin/bash
# Thread leak diagnostic: find which installed libs create ThreadPoolExecutor / tokio runtimes
SP=/opt/review/python/.venv/lib/python*/site-packages

echo "=== ThreadPoolExecutor usage in installed libs ==="
for d in chromadb sentence_transformers transformers tokenizers onnxruntime rerankers huggingface_hub elasticsearch httpx openai sqlalchemy pymysql redis minio confluent_kafka fastapi uvicorn pydantic; do
  hits=$(grep -rln "ThreadPoolExecutor" $SP/$d --include=*.py 2>/dev/null | head -6)
  if [ -n "$hits" ]; then
    echo "--- $d ---"
    echo "$hits"
  fi
done

echo ""
echo "=== which .so contains 'tokio-rt-worker' thread name ==="
find $SP -name "*.so" 2>/dev/null | while read -r f; do
  if strings "$f" 2>/dev/null | grep -q "tokio-rt-worker"; then
    echo "$f"
  fi
done

echo ""
echo "=== python version & chromadb version ==="
/opt/review/python/.venv/bin/python -c "import sys; print(sys.version)"
/opt/review/python/.venv/bin/python -c "import chromadb; print('chromadb', chromadb.__version__)" 2>/dev/null
/opt/review/python/.venv/bin/python -c "import tokenizers; print('tokenizers', tokenizers.__version__)" 2>/dev/null
