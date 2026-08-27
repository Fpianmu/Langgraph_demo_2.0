import { agentBackendUrl } from "./backend-url.ts";

function cleanStoragePath(storagePath: string): string {
  return storagePath.replace(/^\/+/, "").trim();
}

export function storageFileUrl(storagePath: string): string {
  return agentBackendUrl(
    `/api/storage/files/${cleanStoragePath(storagePath)}`,
  );
}

export function storageMarkdownBaseUrl(storagePath: string): string {
  return storageFileUrl(storagePath);
}
