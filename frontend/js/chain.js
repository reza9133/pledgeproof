// Thin wrapper around genlayer-js: reads need no wallet, writes are signed by the EIP-6963 wallet.
const C = window.PP_CONFIG;
const SDK = "https://esm.sh/genlayer-js@1.1.8";
let lib = null, reader = null, writer = null;

async function load() {
  if (lib) return lib;
  const [m, c] = await Promise.all([import(SDK), import(SDK + "/chains")]);
  lib = { createClient: m.createClient, studionet: c.studionet };
  return lib;
}

export const ready = () => /^0x[0-9a-fA-F]{40}$/.test(C.contract || "");

export async function read(fn, args = []) {
  const { createClient, studionet } = await load();
  reader ||= createClient({ chain: studionet });
  return reader.readContract({ address: C.contract, functionName: fn, args });
}

export async function ensureNetwork(provider) {
  const chainId = "0x" + C.chainId.toString(16);
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] });
  } catch {
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId, chainName: "GenLayer Studio Network", rpcUrls: [C.rpc],
        nativeCurrency: { name: "GEN Token", symbol: "GEN", decimals: 18 }, blockExplorerUrls: [C.explorer],
      }],
    });
    try { await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] }); } catch {}
  }
}

export function dropWallet() { writer = null; }

export async function useWallet(account, provider) {
  const { createClient, studionet } = await load();
  writer = createClient({ chain: studionet, account, provider });
}

const REVERT = /\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\][^"'\\\n]*/;
const flat = (x, depth = 0) => {
  if (x == null || depth > 4) return "";
  if (typeof x === "string") return x;
  if (typeof x !== "object") return String(x);
  let t = "";
  if (x instanceof Error) t += [x.message, x.shortMessage, x.details].filter(Boolean).join(" ") + " " + flat(x.cause, depth + 1);
  try { t += " " + JSON.stringify(x, (_, v) => (typeof v === "bigint" ? v.toString() : v)); } catch {}
  return t;
};
export const contractError = (x) => { const m = REVERT.exec(flat(x)); return m ? m[0].trim() : ""; };

// Mirrors scripts/live_e2e.py: read only the transaction's own outcome.
export function outcome(r) {
  if (!r || typeof r !== "object") return { ok: null, error: "" };
  const error = contractError(r);
  const top = r.tx_execution_result_name || r.txExecutionResultName;
  const leaders = r.consensus_data?.leader_receipt;
  const lead = Array.isArray(leaders) ? leaders.filter((x) => x && x.mode !== "validator") : [];
  let ex = [];
  if (typeof top === "string" && top) ex = [top.toUpperCase()];
  else if (lead.length && typeof lead[lead.length - 1].execution_result === "string") ex = [lead[lead.length - 1].execution_result.toUpperCase()];
  const res = String(r.result_name || "").toUpperCase(), st = String(r.status_name || "").toUpperCase();
  if (ex.some((e) => e.includes("ERROR"))) return { ok: false, error: error || "execution error" };
  if (["DISAGREE", "TIMEOUT", "NO_MAJORITY", "MAJORITY_DISAGREE", "DETERMINISTIC_VIOLATION"].includes(res)) return { ok: false, error: error || "consensus result " + res };
  if (["UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"].includes(st)) return { ok: false, error: error || "status " + st };
  if (ex.some((e) => e.includes("SUCCESS") || e.includes("RETURN"))) return { ok: true, error: "" };
  return { ok: null, error };
}

export async function write(fn, args = [], value = 0n, onHash) {
  if (!writer) throw new Error("Connect a wallet first.");
  const hash = await writer.writeContract({ address: C.contract, functionName: fn, args, value });
  onHash?.(hash);
  const receipt = await writer.waitForTransactionReceipt({ hash, status: "ACCEPTED", interval: 3000, retries: 400 });
  const o = outcome(receipt);
  if (o.ok === false) throw new Error(o.error);
  return { hash, receipt, unconfirmed: o.ok === null };
}
