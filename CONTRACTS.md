# Contracts — cross-agent interface decisions

Durable record of interfaces agents depend on across lanes. Update the moment your change affects
another lane's inputs/outputs, **before** merging. Newest at top. Format:

```
## YYYY-MM-DD — <short title>
- Owner: @handle
- Change: what the interface now is (signature / shape / endpoint / event)
- Affects: @handle, @handle
- Migration: what dependents must do
```

---

_No contracts yet._
