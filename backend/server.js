const express = require('express');
const http = require('http');
const { initializeWebSocket } = require('./websocket/socket');

const app = express();
const server = http.createServer(app);

app.get('/', (req, res) => {
  res.send('Backend is running');
});

initializeWebSocket(server);

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});