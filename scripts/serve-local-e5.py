"""Serve cached multilingual E5 embeddings on loopback for FAQ matching."""

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--model-path", default="intfloat/multilingual-e5-base")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(4)
    model = SentenceTransformer(args.model_path, local_files_only=True, device=args.device)
    model.max_seq_length = 256
    model_id = "multilingual-e5-base"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # User text and headers stay out of logs.
            pass

        def send_json(self, status: HTTPStatus, data: dict[str, Any]) -> None:
            content = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ok", "model": model_id})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown route"})

        def do_POST(self) -> None:
            if self.path != "/v1/embeddings":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown route"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 128_000:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                texts = payload["input"]
                if isinstance(texts, str):
                    texts = [texts]
                if (payload["model"] != model_id or not isinstance(texts, list)
                        or not 1 <= len(texts) <= 32
                        or any(not isinstance(text, str) or not 1 <= len(text) <= 4000 for text in texts)):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid embedding request"})
                return
            # Both sides are questions, so use the same E5 prefix for symmetric matching.
            vectors = model.encode(
                ["query: " + text for text in texts], normalize_embeddings=True,
                batch_size=8, show_progress_bar=False,
            ).tolist()
            self.send_json(HTTPStatus.OK, {"model": model_id, "data": [
                {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
            ]})

    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Local {model_id} service on http://127.0.0.1:{args.port}/v1", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
