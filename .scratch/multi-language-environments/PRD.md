# Multi-language Language Environments

Status: ready-for-agent

Implementation status: not started

## Purpose

Extend the Runner-owned Language Environment Catalog from one production Python
environment to the initial Tournament language set: Python, Go, Java,
TypeScript, C#, and optional Rust.

Each production Language Environment must own the complete source-validation,
build, wrapper, Seed Adapter, readiness, entrypoint, runtime, and conformance
contract needed to turn Team Source into a Final-Validated Bot Artifact. The
generic Runner must select those assets from immutable catalog data instead of
selecting Python directly.

## Runtime policy

Select toolchains when preparing a Language Environment release, then pin their
exact multi-platform identities. For ecosystems with an upstream LTS
designation, select the latest upstream-supported LTS. For ecosystems without
an LTS designation, select the latest upstream-supported stable release.
TypeScript selects the latest supported Node.js LTS plus an exactly pinned,
compatible stable TypeScript compiler.

`latest`, moving release channels, and mutable image tags are never Catalog
Release inputs. A runtime update creates a new Language Environment identity and
Catalog Release.

Each compiled-language environment may distinguish its pinned build toolchain
from its smaller execution runtime. The catalog must publish enough immutable
build-toolchain information for the companion Team Template to run its own
participant-facing build-and-test script in Docker without copying runtime
authority into that repository.

## Delivery order

1. Prove a second executable Language Environment through the generic Runner.
2. Apply the runtime policy to Python and publish the first catalog contract
   consumable by native-or-Docker Team Template checks.
3. Add and publish Go as the first new production Language Environment.
4. Add Java, TypeScript, and C# after the Go tracer bullet proves the seam.
5. Add Rust optionally against the same production acceptance bar.

## Cross-repository boundary

ADR 0005 remains unchanged. The Runner owns and tests Language Environments and
never fetches, imports, or tests the companion Team Template repository. The
companion repository may consume an exact published Catalog Release and use its
immutable build-toolchain coordinates. Its corresponding language ticket is
blocked until the Runner ticket publishes that release; the Runner ticket is
not blocked by the Team Template.

## Completion

This effort is complete when every required language has a production Language
Environment in an immutable Catalog Release, passes equivalent ARM64 and AMD64
build and conformance checks, and can be selected throughout validation,
certification, preparation, planning, Tournament execution, retention, and
catalog publication without Python-specific branching in generic Runner code.
Rust is complete only if it meets that same bar, but it does not gate completion
of the required language set.
