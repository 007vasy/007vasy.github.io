const express = require("express");
const path = require("path");

const app = express();
const port = process.env.PORT || 65000;
// const file_to_convert = process.env.FILE_TO_CONVERT || "";

// if (file_to_convert != "") {
//   console.log("asd");
// }

app.use(express.static(path.join(__dirname, "/docs")));

// sendFile will go here
app.get("/", function (req, res) {
  res.sendFile(path.join(__dirname, "index.html"));
});

app.listen(port);
console.log("Server started at http://localhost:" + port);
