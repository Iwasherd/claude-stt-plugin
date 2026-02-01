
==========
== CUDA ==
==========

CUDA Version 12.8.1

Container image Copyright (c) 2016-2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.

This container image and its contents are governed by the NVIDIA Deep Learning Container License.
By pulling and using the container, you accept the terms and conditions of this license:
https://developer.nvidia.com/ngc/nvidia-deep-learning-container-license

A copy of this license is made available in this container at /NGC-DL-CONTAINER-LICENSE for your convenience.

WARNING: The NVIDIA Driver was not detected.  GPU functionality will not be available.
   Use the NVIDIA Container Toolkit to start this container with GPU support; see
   https://docs.nvidia.com/datacenter/cloud-native/ .

import logging
import os
import tempfile
import time
from contextlib import asynccontextmanager

import torch
import whisper
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

# OpenTelemetry imports
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Configure logging
tool_logger = logging.getLogger("whisper_service")
tool_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
tool_logger.addHandler(handler)

# Configure OpenTelemetry
OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")
SERVICE_NAME = "stt-service"

# Set up OpenTelemetry resource
resource = Resource.create({
    "service.name": SERVICE_NAME,
    "service.version": "1.0.0"
})

# Configure tracing
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

# OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)
span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Configure metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True),
    export_interval_millis=30000
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
meter = metrics.get_meter(__name__)

# Configure OTLP logging (same pattern as Go services)
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

# Create OTLP log exporter (same as Go services)
otlp_log_exporter = OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True)

# Create logger provider with the same resource
logger_provider = LoggerProvider(resource=resource)
set_logger_provider(logger_provider)

# Add OTLP log processor (same pattern as Go services)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

# Create OTLP handler and add to our logger
otlp_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
tool_logger.addHandler(otlp_handler)

# OpenTelemetry logging instrumentation
LoggingInstrumentor().instrument(set_logging_format=True)

# Prometheus metrics
REQUEST_COUNT = Counter('stt_requests_total', 'Total STT requests', ['language', 'target_language', 'status'])
REQUEST_DURATION = Histogram('stt_request_duration_seconds', 'STT request duration in seconds', ['language', 'target_language'])
ACTIVE_REQUESTS = Gauge('stt_active_requests', 'Number of active STT requests')
PROCESSING_TIME = Histogram('stt_processing_time_seconds', 'Time spent processing audio', ['operation'])

# Start Prometheus metrics server
start_http_server(9464)

# FastAPI lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    tool_logger.info("Initializing Whisper service...")
    yield
    tool_logger.info("Shutting down Whisper service.")


app = FastAPI(lifespan=lifespan)

# Instrument FastAPI with OpenTelemetry
FastAPIInstrumentor.instrument_app(app)

# Load Whisper ASR model
tool_logger.info("Loading Whisper model (large)...")
model = whisper.load_model("large")
tool_logger.info("Whisper model loaded.")

# Load open-source translation model M2M100 for many-to-many translation
tool_logger.info("Loading M2M100 translation model...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
mt_model_name = "facebook/m2m100_418M"
tokenizer = M2M100Tokenizer.from_pretrained(mt_model_name)
mt_model = M2M100ForConditionalGeneration.from_pretrained(mt_model_name).to(device)
supported_langs = {"ru", "uk", "en", "cs", "es", "pl"}
tool_logger.info("M2M100 model loaded.")


@app.post("/chunk/")
async def process_chunk(
        session_id: str = Form(...),
        chunk_id: int = Form(...),
        language: str = Form(None),  # source language code (None for auto-detection)
        target_language: str = Form("en"),  # target language code
        file: UploadFile = File(...)
):
    start_time = time.monotonic()
    
    # Increment active requests gauge
    ACTIVE_REQUESTS.inc()
    
    # Start tracing span
    with tracer.start_as_current_span("process_chunk") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("chunk_id", chunk_id)
        span.set_attribute("language", language)
        span.set_attribute("target_language", target_language)
        span.set_attribute("filename", file.filename or "unknown")
        
        tool_logger.info(f"Session {session_id} chunk {chunk_id}: received file {file.filename} (content_type: {file.content_type})")
        
        try:
            if target_language not in supported_langs:
                REQUEST_COUNT.labels(language=language, target_language=target_language, status="error").inc()
                span.set_attribute("error", True)
                span.set_attribute("error.message", f"Unsupported target_language: {target_language}")
                raise HTTPException(status_code=400, detail=f"Unsupported target_language: {target_language}")

            # Save incoming audio file (support multiple formats)
            data = await file.read()
            span.set_attribute("file_size_bytes", len(data))
            
            # Determine file extension from filename or content type
            file_extension = '.wav'  # default
            if file.filename:
                if file.filename.lower().endswith(('.mp3', '.m4a', '.mp4')):
                    file_extension = '.mp3'
                elif file.filename.lower().endswith(('.ogg', '.oga')):
                    file_extension = '.ogg'
                elif file.filename.lower().endswith('.flac'):
                    file_extension = '.flac'
                elif file.filename.lower().endswith(('.wav', '.wave')):
                    file_extension = '.wav'
            
            # Create temp file with appropriate extension
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                # ASR via Whisper
                with tracer.start_as_current_span("whisper_transcribe") as whisper_span:
                    transcribe_start = time.monotonic()
                    # Use auto-detection if language is None, otherwise use specified language
                    if language and language.strip():
                        res = model.transcribe(tmp_path, language=language)
                        detected_language = language
                    else:
                        res = model.transcribe(tmp_path)  # Auto-detect language
                        detected_language = res.get("language", "en")  # Whisper provides detected language
                    raw_text = res.get("text", "").strip()
                    transcribe_duration = time.monotonic() - transcribe_start
                    
                    whisper_span.set_attribute("transcribe_duration", transcribe_duration)
                    whisper_span.set_attribute("text_length", len(raw_text))
                    whisper_span.set_attribute("detected_language", detected_language)
                    PROCESSING_TIME.labels(operation="transcribe").observe(transcribe_duration)

                    tool_logger.info(f"Raw text: {raw_text} (detected language: {detected_language})")

                # Translation via M2M100
                with tracer.start_as_current_span("m2m100_translate") as translate_span:
                    translate_start = time.monotonic()
                    # Use detected language for translation
                    tokenizer.src_lang = detected_language
                    inputs = tokenizer(raw_text, return_tensors="pt").to(device)
                    generated_tokens = mt_model.generate(
                        **inputs,
                        forced_bos_token_id=tokenizer.get_lang_id(target_language)
                    )
                    translation = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0].strip()
                    translate_duration = time.monotonic() - translate_start
                    
                    translate_span.set_attribute("translate_duration", translate_duration)
                    translate_span.set_attribute("translation_length", len(translation))
                    PROCESSING_TIME.labels(operation="translate").observe(translate_duration)
                    
                    tool_logger.info(f"Translated text: {translation}")

            except Exception as e:
                error_language = detected_language if 'detected_language' in locals() else (language or "unknown")
                REQUEST_COUNT.labels(language=error_language, target_language=target_language, status="error").inc()
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(e))
                tool_logger.error(f"Error processing chunk: {e}")
                raise HTTPException(status_code=500, detail=str(e))

            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

            elapsed = time.monotonic() - start_time
            
            # Record metrics with detected language
            REQUEST_COUNT.labels(language=detected_language, target_language=target_language, status="success").inc()
            REQUEST_DURATION.labels(language=detected_language, target_language=target_language).observe(elapsed)
            
            # Set span attributes
            span.set_attribute("processing_time", elapsed)
            span.set_attribute("success", True)
            
            tool_logger.info(f"Finished processing: session={session_id}, chunk={chunk_id} in {elapsed:.2f}s")

            return {
                "session_id": session_id,
                "chunk_id": chunk_id,
                "raw_text": raw_text,
                "translation": translation,
                "processing_time_s": round(elapsed, 2),
                "detected_language": detected_language
            }
            
        finally:
            # Decrement active requests gauge
            ACTIVE_REQUESTS.dec()
