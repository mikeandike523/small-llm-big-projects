# CLAUDE.md -- Environment and Development Tips for this Project

## project Overview

This project is called "small-llm-big-projects" or "slbp" for short.
The goal is to create an agentic loop that is compatible with smaller models
and avoids the need for massive 100 or more billion parameter models.

The project uses easy-to-use session and project memory tools to bolster
and agent's decision making, making smaller models more viable.

## Project Structure

The project consists of a terminal command and its implementation in `src/**`
as well as a ui, made in react with vite, in `ui/**`

Some of the most important commands are `slbp server run`
hich starts the agentic session orchestration server

and `slbp session new` which starts a new agentic loop session, and opens the ui
in a browser with the new session id

## Development Tips

- Before each new feature, review your recent memory files to know what is going on in the project at this time
- Prefer to take more memory notes rather than less. Its good to keep track of what is going on

