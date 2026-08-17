#!/usr/bin/env python3
"""Minimal KURE embedding HTTP server for local/dev RAG integration.

Expected request:
  POST /embed
  {"model":"nlpai-lab/KURE-v1","input":["질문"]}

Response:
  {"model":"nlpai-lab/KURE-v1","embeddings":[[...]],"dimensions":1024}
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


DEFAULT_MODEL = "nlpai-lab/KURE-v1"


class EmbeddingHandler(BaseHTTPRequestHandler):
    model = None
    model_name = DEFAULT_MODEL
    batch_size = 8

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return

        self.respond_json({"status": "ok", "model": self.model_name})

    def do_POST(self) -> None:
        if self.path != "/embed":
            self.send_error(404)
            return

        try:
            payload = self.read_json()
            inputs = self.normalize_inputs(payload.get("input"))
            embeddings = self.model.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors = [[float(value) for value in embedding] for embedding in embeddings]
            self.respond_json(
                {
                    "model": payload.get("model") or self.model_name,
                    "embeddings": vectors,
                    "dimensions": len(vectors[0]) if vectors else 0,
                }
            )
        except ValueError as error:
            self.respond_json({"error": str(error)}, status=400)
        except Exception as error:
            self.respond_json({"error": str(error)}, status=500)

    def log_message(
            self,
            format: str,
            *args: Any
    ) -> None:
        print("%s - %s" % (self.address_string(), format % args))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Request body is required")

        raw_body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def normalize_inputs(self, value: Any) -> list[str]:
        if isinstance(value, str):
            inputs = [value]
        elif isinstance(value, list):
            inputs = [str(item) for item in value if str(item).strip()]
        else:
            raise ValueError("input must be a string or array of strings")

        if not inputs:
            raise ValueError("input must not be empty")
        return inputs

    def respond_json(
            self,
            payload: dict[str, Any],
            status: int = 200
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    from sentence_transformers import SentenceTransformer

    args = parse_args()
    EmbeddingHandler.model_name = args.model
    EmbeddingHandler.batch_size = args.batch_size
    EmbeddingHandler.model = SentenceTransformer(args.model)

    server = ThreadingHTTPServer((args.host, args.port), EmbeddingHandler)
    print(f"KURE embedding server listening on http://{args.host}:{args.port}")
    print("Health check: GET /health")
    print("Embedding endpoint: POST /embed")
    server.serve_forever()


if __name__ == "__main__":
    main()
