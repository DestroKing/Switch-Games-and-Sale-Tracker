import { collect } from "./cli/collect.ts";
import { probe } from "./cli/probe.ts";
import { refreshRates } from "./fx/rates.ts";

const command = process.argv[2];

switch (command) {
  case "probe":
    await probe(true);
    break;
  case "collect":
    await collect();
    break;
  case "fx": {
    const rates = await refreshRates(["USD"]);
    for (const r of rates) console.log(`${r.base}->INR ${r.rate} (ECB ${r.rateDate})`);
    break;
  }
  case "menu":
  case undefined:
    await import("./menu.ts");
    break;
  default:
    console.log("usage: bun run src/index.ts <menu|probe|collect|fx>");
    process.exit(1);
}
