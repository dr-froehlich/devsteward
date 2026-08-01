# Requirements Index — Phase 5 Integration

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | ArduinoJson ESP-IDF component | done | [REQ-001](REQ-001.md) | – |
| REQ-002 | Message and MessageQueue (thread-safe) | done | [REQ-002](REQ-002.md) | REQ-001 |
| REQ-003 | MQTT subscription routing | done | [REQ-003](REQ-003.md) | REQ-002 |
| REQ-004 | WhoAmI device identity | done | [REQ-004](REQ-004.md) | – |
| REQ-005 | Configurable base class | done | [REQ-005](REQ-005.md) | REQ-002, REQ-003 |
| REQ-006 | LittleFS configuration persistence | done | [REQ-006](REQ-006.md) | REQ-001 |
| REQ-007 | UI adapter class | done | [REQ-007](REQ-007.md) | – |
| REQ-008 | Room class | done | [REQ-008](REQ-008.md) | REQ-005, REQ-007 |
| REQ-009 | Thermo class | done | [REQ-009](REQ-009.md) | REQ-008, REQ-004, REQ-006 |
| REQ-010 | main.cpp integration | done | [REQ-010](REQ-010.md) | REQ-009 |
| REQ-011 | Python CLI tool for device deployment and maintenance | draft | [REQ-011](REQ-011.md) | – |
| REQ-012 | Python MQTT regression tester (thermotest) | draft | [REQ-012](REQ-012.md) | REQ-011 |

## Dependency graph

```
REQ-001 (ArduinoJson)──┬──REQ-002 (Message)──┬──REQ-003 (MQTT routing)──┐
                        │                     │                          │
                        └──REQ-006 (LittleFS) │                          │
                                              └──REQ-005 (Configurable)──┤
REQ-004 (WhoAmI)────────────────────────────────────────────────────────┤
                                                                         │
REQ-007 (UI adapter)──────────────────────────REQ-008 (Room)────────────┤
                                                                         │
                                               REQ-009 (Thermo)─────────┤
                                                                         │
                                               REQ-010 (main.cpp)───────┘
```

## Implementation order

Items without dependencies can be worked on in parallel. Suggested serial order:

1. REQ-001 (ArduinoJson) + REQ-004 (WhoAmI) + REQ-007 (UI adapter) — no dependencies, parallelizable
2. REQ-002 (Message) + REQ-006 (LittleFS) — depend only on REQ-001
3. REQ-003 (MQTT routing) — depends on REQ-002
4. REQ-005 (Configurable) — depends on REQ-002, REQ-003
5. REQ-008 (Room) — depends on REQ-005, REQ-007
6. REQ-009 (Thermo) — depends on REQ-008, REQ-004, REQ-006
7. REQ-010 (main.cpp integration) — depends on REQ-009

New requirement template: [REQ-xxx.md](REQ-xxx.md)
