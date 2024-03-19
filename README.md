# Nano Election Visualizer

Nano Election Visualizer is a Dockerized web application designed to provide real-time insights into Nano cryptocurrency elections. It allows users to visualize both confirmed and unconfirmed elections, offering a deep dive into the specifics of each election. By leveraging this tool, users can explore the details of what representative voted on a hash, including confirmation duration, account balance, and transaction amount. The core feature is the overview of who voted on the hash (normal and final votes) and the comparison of each node's response time relative to the first voter.


## Requirements

- Docker and Docker Compose installed on your machine.
- An internet connection to pull necessary Docker images and dependencies.

## Setup Instructions

1. Clone the project from GitHub:

```
git clone https://github.com/gr0vity-dev/nano-election-visu.git
cd nano-election-visu
```


2. Create a `.env` file in the root directory of the project with the following content, replacing the placeholders with your actual Nano node details:
```
WS_URL=<WebSocket URL>
RPC_URL=<RPC URL>
RPC_USERNAME=<RPC Username>
RPC_PASSWORD=<RPC Password>
```
3. Build and start the Docker containers:
```
docker compose --profile memcache up -d
docker compose build && docker compose up -d
```


## Usage

After successfully starting the Docker containers, open a web browser and go to `http://localhost:5003` to access the Nano Election Visualizer.

- **Overview Page**: This page is split into confirmed and unconfirmed elections, providing a broad overview of ongoing and completed elections.

- **Election Detail Page**: By clicking on an election, you can view all the details related to what representative voted on a hash. This includes confirmation duration, account balance, transaction amount, and an overview of who voted on the hash (normal and final votes) along with the time it took each node compared to the first voter.

## Contributing

Feel free to fork the project, make changes, and submit pull requests to contribute to the development of the Nano Election Visualizer.

