"""
High-level tests for the pipeline's core infrastructure.

These tests verify that the key modules work correctly at an integration
level — they do NOT test internal implementation details, keeping them
resilient to refactoring.

No network calls, no Claude API — everything is tested with fakes/mocks.
"""

