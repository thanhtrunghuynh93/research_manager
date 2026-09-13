"""Authorized export of research records (UI-06, requirements §11 "Portability").

A bounded context rather than a router, because assembling a bundle is work: it spans reporting,
projects, assessment, and evidence, and it has to do so without acquiring a second permission
model. Every record here is read through the owning module's `service.py`, so a download carries
exactly the authority of the person who asked for it and nothing more.

The layered import contract in `pyproject.toml` places `app.exports` above `app.assessment` and
below `app.assistant`, which is what it needs: it reads everything below and nothing depends on it
except the API.
"""
