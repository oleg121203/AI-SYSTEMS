Ось адаптована версія твого тексту у форматі README.md — повністю готова для вставки в репозиторій GitHub або іншу документацію:

⸻



# 🧠 AI-SYSTEMS Architecture

AI-SYSTEMS is a modular AI architecture designed for automated software development through prompt-based configuration. It provides a multi-agent environment with clearly defined responsibilities, coordinated through stages and structured message routing.

## 🏗️ Agents

Each agent is responsible for a distinct functional role:

- **AI1 — Coordinator**  
  Coordinates tasks and assigns them to other agents based on the current pipeline stage.

- **AI2 — Worker (Code/Doc Generator)**  
  Generates code, documentation, or other artifacts depending on the assigned prompt.

- **AI3 — Structure Manager**  
  Monitors architecture, validates prompt structures, and manages overall system integrity.

All agents support message queuing and WebSocket communication with the MCP API.

## ⚙️ Configuration Structure

The system uses functional prompt stages and hierarchical agent IDs to configure workflows:

### 🔢 Stages
| Stage | Description                |
|-------|----------------------------|
| f100  | Initial planning           |
| f101  | Task detailing             |
| f102  | Code generation            |
| f103  | Linting & formatting       |
| f104  | Documentation generation   |

### 🧩 Agent IDs

Agents follow a hierarchical naming convention:

- `ai2.1`, `ai2.2`, ... — Workers of type AI2
- `ai3.1` — Main structure manager

This makes load balancing and task routing scalable.

## 🔌 MCP API

All inter-agent communication flows through a central **MCP (Main Control Point)** API:

- Queued task management
- Logging
- Status monitoring
- WebSocket-based real-time updates

## 📈 Dashboard

The system includes a frontend dashboard to:

- Monitor worker status
- View logs and results
- Control pipeline execution in real-time

## 🛠️ Roadmap

- [x] Core prompt execution logic  
- [x] Multi-agent configuration  
- [x] WebSocket communication  
- [ ] GitHub Actions integration  
- [ ] Persistent memory and task queue  
- [ ] Knowledge base integration  
- [ ] Local LLM support (Ollama)


⸻

Author: [Oleg Kizyma (call sign 6699)]
License: MIT
Language: Python 3.11+, FastAPI, TypeScript

---
