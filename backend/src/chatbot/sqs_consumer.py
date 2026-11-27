# SQSConsumer has been decoupled into the standalone 'consumer' service.
# This file provides an optional fallback if consumer is in the Python path.
try:
    from consumer.sqs_consumer import SQSConsumer
    __all__ = ["SQSConsumer"]
except ImportError:
    SQSConsumer = None
    __all__ = []

