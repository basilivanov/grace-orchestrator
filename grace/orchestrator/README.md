# Legacy GRACE XML CLI orchestrator

This package is legacy SolarSage XML/CLI tooling.

It supports only:

- reading `grace/development-plan.xml`;
- showing wave status;
- simple packet markdown validation.

It is not the active runtime execution pipeline.

Active architect/worker/packet execution lives in:

```
src/grace_control/
```

Do not add verifier, reviewer, acceptance pipeline, merge gates, or self-evolution runtime logic here.
