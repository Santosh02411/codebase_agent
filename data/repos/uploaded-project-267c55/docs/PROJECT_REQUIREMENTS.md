# Project Requirements

## 1. Purpose
Build a delivery status update system that works fully offline and syncs
reliably once internet connectivity is restored, aimed at delivery agents
operating in low-network areas (both urban dead zones and rural regions).

## 2. Target Users
- **Delivery Agent** — updates order status on their device, often offline
- **Dispatcher / Manager** — views synced delivery statuses on a dashboard

## 3. Functional Requirements
| ID | Requirement |
|----|-------------|
| FR1 | Agent can mark a delivery as: picked up, out for delivery, delivered, or failed attempt |
| FR2 | All status updates must be saved locally (IndexedDB) even with zero connectivity |
| FR3 | When connectivity returns, the app automatically syncs all pending updates to the backend |
| FR4 | If the same delivery record was updated in two places, the system resolves the conflict automatically (last-write-wins by timestamp) |
| FR5 | Dispatcher dashboard shows current status of all deliveries and their sync state (pending/synced) |
| FR6 | Failed sync attempts are retried automatically |

## 4. Non-Functional Requirements
| ID | Requirement |
|----|-------------|
| NFR1 | Must run entirely on free tools — no paid services or hardware |
| NFR2 | Must work with zero internet connection for the agent-facing app |
| NFR3 | Sync engine logic must be explainable in an interview setting (clear, documented design decisions) |
| NFR4 | Codebase must be clean enough to extend later (e.g. to a different use case reusing the sync engine) |

## 5. Out of Scope (for v1)
- Real-time GPS tracking
- Push notifications
- Multi-agent role permissions beyond agent/dispatcher
- Payment or order-creation features

## 6. Success Criteria
- Agent can go fully offline, update several deliveries, reconnect, and see all
  changes correctly reflected on the dispatcher dashboard with conflicts resolved
  sensibly
- Project can be demoed end-to-end in an interview in under 5 minutes
