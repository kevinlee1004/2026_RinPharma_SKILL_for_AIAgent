# Skill for AI Agents Workshop

Welcome to the **Skill for AI Agents Workshop**! This repository contains materials, instructions, and practical use cases for learning how to build, deploy, and manage reusable "Skills" for AI agents. 

The workshop focuses on turning domain expertise—specifically in pharmaceutical data analysis with CDISC standards—into on-demand, discoverable capabilities for AI agents using **Claude Code** and **Positron Pro**.

## 📚 Table of Contents
- [Overview](#overview)
- [Prerequisites & Setup](#prerequisites--setup)
- [Repository & Data Setup](#repository--data-setup)
- [Workshop Use Cases](#workshop-use-cases)
- [Skill Architecture](#skill-architecture)
- [Helpful Resources](#helpful-resources)

---

## 🎯 Overview
An AI agent is an LLM-powered system that perceives its environment, reasons about the next step, and takes action with tools. Effective agents combine three ingredients:
1. **A capable model** (Reasoning and language ability)
2. **Tools & data access** (Search, code, files, and APIs)
3. **Reusable expertise** (Skills that bundle instructions, references, and scripts)

This workshop focuses on the **third ingredient**: replacing repeated prompting with reusable skills that an agent can load on demand, ensuring consistent, repeatable, and accurate workflows.

---

## ⚙️ Prerequisites & Setup

### 1. Positron Pro Environment
- Navigate to [workshop.posit.team](https://workshop.posit.team/) and sign up or sign in.
- Create a new session and launch **Positron Pro**.
- Open the folder with your name and create a Python Environment (ensure both Python and R are set up).

### 2. Claude Code Configuration
- Start Claude Code in the terminal.
- ⚠️ **Important**: Change the model to **Haiku**. Otherwise, your token limit might be exhausted before the end of the course.

---

## 📂 Repository & Data Setup

Run the following steps in your terminal to prepare the required data and skills:

1. **Clone the CDISC Pilot Data**:
   ```bash
   git clone https://github.com/cdisc-org/sdtm-adam-pilot-project.git