const sdvImport = require("sportsdataverse");
const Papa = require("papaparse");
const fs = require("fs");

const sdv = sdvImport.default;

async function main() {
  const result = await sdv.mbb.getSchoolCommits("Clemson", 2025);

  const rows = Array.isArray(result)
    ? result
    : Array.isArray(result.data)
      ? result.data
      : [result];

  const csv = Papa.unparse(rows);

  fs.writeFileSync("clemson_commits_2016.csv", csv);
}

main();