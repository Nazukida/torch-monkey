"""Server-side persistence package for the Torch Monkey web client.

:mod:`python.api.store` mirrors the Electron ``DatabaseHandler`` so the browser
sees the exact same camelCase ``MotionData`` / ``ProjectFile`` shapes the desktop
app produces, reusing ``database/schema.sql`` verbatim.
"""
