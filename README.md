# 🌊 FloatChat - AI-Powered Conversational Interface for ARGO Ocean Data Discovery and Visualization

## 🚀 Project Overview

**FloatChat** is an advanced AI-powered conversational system designed to simplify access to and exploration of oceanographic data, specifically focusing on ARGO float data. The system empowers users—ranging from domain experts to decision-makers and non-technical personnel—to query, analyze, and visualize ocean data using simple natural language queries, without needing deep technical expertise or familiarity with complex data formats.

---

## 🌐 Background

Oceanographic data is vast, complex, and highly heterogeneous. It includes a wide variety of sources such as:
- **Satellite observations**
- **In-situ measurements** (like CTD casts, Argo floats, and BGC sensors)

Among these, the **Argo Program** is a global initiative that deploys autonomous profiling floats across the world’s oceans. These floats collect essential ocean variables such as:
- Temperature
- Salinity
- Bio-Geo-Chemical (BGC) parameters

Data from these floats is stored in **NetCDF format**—a complex, multidimensional data structure used widely in scientific data analysis.

However, accessing, querying, and visualizing this data traditionally requires:
- Domain knowledge
- Technical expertise
- Proficiency in tools like Python, NetCDF libraries, SQL databases, and GIS tools

The goal of FloatChat is to **democratize access** to ARGO data by building an intuitive, interactive AI system that removes these barriers.

---

## 🎯 Problem Statement

The challenge is to develop a system that enables users to interact with ARGO ocean data via **natural language queries** and gain insights through visual and tabular summaries.

### Key Objectives:
- Ingest and convert ARGO NetCDF files into structured formats like **SQL** or **Parquet** for easier querying.
- Store metadata and data summaries in a **vector database** (e.g., FAISS or Chroma) to facilitate efficient retrieval.
- Use advanced **Retrieval-Augmented Generation (RAG)** techniques combined with **multimodal Large Language Models (LLMs)** such as GPT, QWEN, LLaMA, or Mistral, to translate user questions into database queries.
- Provide an interactive **dashboard interface** to visualize ARGO float data (e.g., mapped trajectories, depth-time plots).
- Implement a **chatbot interface** where users can simply ask questions like:
    - “Show me salinity profiles near the equator in March 2023”
    - “Compare BGC parameters in the Arabian Sea for the last 6 months”
    - “What are the nearest ARGO floats to this location?”

---

## ⚡ Expected Solution Architecture

### 1. **Data Ingestion and Processing**
- Convert raw **ARGO NetCDF files** into structured formats:
    - **Relational Database** (PostgreSQL) for structured storage of profiles, measurements, timestamps, and metadata.
    - **Parquet Files** for efficient columnar storage and faster data access.
- Extract and summarize metadata for fast lookup and retrieval.

### 2. **Vector Database**
- Store metadata summaries and vector embeddings of data chunks in a **FAISS or Chroma vector database**.
- Enable semantic search and similarity-based retrieval of relevant data points.

### 3. **LLM-Based Natural Language Interface**
- Implement a **Retrieval-Augmented Generation (RAG)** pipeline.
    - User natural language input → Semantic search in vector DB → Relevant context retrieved → LLM generates SQL query and/or formatted answer.
    - Use the **Model Context Protocol (MCP)** for structured and scalable interaction between the backend and LLM.
- Example Query Flow:
    1. User types: “Show me salinity profiles near the equator in March 2023”
    2. The system converts this into SQL:
        ```sql
        SELECT * FROM argo_data WHERE region = 'Equator' AND month = 'March' AND year = 2023;
        ```
    3. Data is retrieved and visualized.

### 4. **Interactive Visualization Dashboard**
- Built using tools like **Streamlit** or **Dash**.
- Visualizations include:
    - **Mapped Float Trajectories**: Interactive maps showing float movements.
    - **Depth-Time Plots**: Time series of measurements at different depths.
    - **Parameter Comparisons**: Side-by-side comparison of temperature, salinity, BGC parameters.
    - **Profile Comparisons** and more.
- Export options: CSV, ASCII, NetCDF formats.

### 5. **Chatbot Interface**
- Conversational interface where users can ask questions in natural language.
- The chatbot provides:
    - Direct answers
    - Links to visualizations
    - Suggested queries and guidance for exploration.

---

## ⚙️ Technologies Used

| Layer | Technologies |
|-------|------------|
| Data Ingestion | Python, netCDF4, Pandas, Pyarrow (Parquet format) |
| Database | PostgreSQL (Relational), FAISS/Chroma (Vector DB) |
| AI Model | GPT / QWEN / LLaMA / Mistral (via MCP protocol) |
| Retrieval | RAG Pipeline |
| Frontend | Streamlit / Dash |
| Visualization | Plotly, Leaflet, Cesium |
| Deployment | Docker, Streamlit sharing, Flask API backend |

---

## ✅ Proof of Concept (PoC)

The system will demonstrate the following use cases:
1. Ingest sample Indian Ocean ARGO float data.
2. Interactive chatbot that successfully interprets natural language queries.
3. Visual dashboards for:
    - Mapping ARGO float trajectories
    - Depth vs Time parameter plots
    - Comparing BGC data across regions and timeframes
4. Export of queried datasets in tabular and NetCDF formats.
5. Extensibility designed to incorporate:
    - BGC floats
    - Gliders
    - Buoy data
    - Satellite data

---

## 🎯 Future Scope

- Support for multimodal data (images, charts).
- Integration with real-time ARGO float data updates.
- Advanced alerting system for anomaly detection.
- Multilingual support for queries.

---

## 📚 Acronyms

| Acronym | Meaning |
|---------|---------|
| NetCDF | Network Common Data Format |
| CTD | Conductivity Temperature and Depth |
| BGC | Bio-Geo-Chemical floats |
| RAG | Retrieval-Augmented Generation |
| MCP | Model Context Protocol |

---

## 👥 Organization

**Ministry of Earth Sciences (MoES)**  
**Department:** Indian National Centre for Ocean Information Services (INCOIS)

---
