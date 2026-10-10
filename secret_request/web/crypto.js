export function b64(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function encryptSecret(value, publicKey, requestId) {
  const plain = new TextEncoder().encode(value);
  if (!plain.length || plain.length > 65536 || value.includes("\0")) throw new Error("size");
  const rsa = await crypto.subtle.importKey("jwk", { ...publicKey, ext: true, key_ops: ["encrypt"] },
    { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
  const aes = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce,
    additionalData: new TextEncoder().encode("secret-request:v1:" + requestId) }, aes, plain);
  const rawKey = await crypto.subtle.exportKey("raw", aes);
  const wrapped = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsa, rawKey);
  plain.fill(0);
  return { v: 1, wrapped_key: b64(wrapped), nonce: b64(nonce), ciphertext: b64(ciphertext) };
}
