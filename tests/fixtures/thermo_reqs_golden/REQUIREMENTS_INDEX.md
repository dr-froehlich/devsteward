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
| REQ-011 | Python CLI tool for device deployment and maintenance | superseded | [REQ-011](REQ-011.md) | – |
| REQ-012 | Python MQTT regression tester (thermotest) | superseded | [REQ-012](REQ-012.md) | REQ-026, REQ-011 |
| REQ-013 | Fix self-deadlock in message-queue processing (get → sendStatus re-lock) | done | [REQ-013](REQ-013.md) | REQ-008, REQ-009 |
| REQ-014 | Fix lock-order deadlock between MqttRouter and esp-mqtt API lock | done | [REQ-014](REQ-014.md) | REQ-003 |
| REQ-015 | WiFi reconnection must never give up | done | [REQ-015](REQ-015.md) | – |
| REQ-016 | Deliver discovery/status/config reliably after MQTT connect | done | [REQ-016](REQ-016.md) | REQ-009, REQ-010 |
| REQ-017 | Actuator cycle planner — fix unsigned underflow and define saturation semantics | done | [REQ-017](REQ-017.md) | – |
| REQ-018 | Move status reporting out of the FreeRTOS timer daemon task | done | [REQ-018](REQ-018.md) | REQ-009, REQ-010 |
| REQ-019 | Restore reportingInterval and status-on-change reporting | done | [REQ-019](REQ-019.md) | REQ-018 |
| REQ-020 | Handle MQTT messages larger than the RX buffer (fragmented events) | done | [REQ-020](REQ-020.md) | REQ-003 |
| REQ-021 | Enable OTA rollback (app rollback + pending-verify actually active) | done | [REQ-021](REQ-021.md) | – |
| REQ-022 | Input validation and multi-room UI fixes (iTime=0 NaN, encoder target fan-out) | done | [REQ-022](REQ-022.md) | REQ-008 |
| REQ-023 | Implement room_output slave duty follower | done | [REQ-023](REQ-023.md) | REQ-008, REQ-013, REQ-017 |
| REQ-024 | Restore MQTT log forwarding (info/<deviceId>/log/<level>) | done | [REQ-024](REQ-024.md) | REQ-010 |
| REQ-025 | Fix min/max cycle energy model in the actuator PWM planner | done | [REQ-025](REQ-025.md) | REQ-017 |
| REQ-026 | Fleet management CLI (thermoctl v2) — async core, survey & inventory, OTA flash | done | [REQ-026](REQ-026.md) | REQ-011 |
| REQ-027 | Firmware regression suite as `thermoctl test` (supersedes REQ-012) | done | [REQ-027](REQ-027.md) | REQ-026, REQ-016, REQ-019, REQ-020, REQ-022, REQ-023, REQ-024 |
| REQ-028 | Device-level rooms-set must merge, not clobber; device routes must survive a rooms rebuild | done | [REQ-028](REQ-028.md) | REQ-003, REQ-008, REQ-009, REQ-027 |

REQ-013 … REQ-022 are follow-ups from the migration code review, see
[`doc/reports/2026-07-02_migration_code_review.md`](../reports/2026-07-02_migration_code_review.md)
(severity ranking and recommended order in report §1 and §8: REQ-013/014 first,
then REQ-015/016/021; implementation plans in `doc/plans/refactor-0*.md`).

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
