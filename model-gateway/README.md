# Model Gateway - Module 5 
 
Couche d'abstraction des modeles LLM locaux via Ollama. 
 
## Routes 
- POST /v1/generate : generation avec streaming 
- POST /v1/chat : conversation avec streaming 
- POST /v1/embeddings : vectorisation pour le RAG 
- GET /v1/models : liste des modeles 
 
## Lancer 
uvicorn main:app --reload --port 8004
