export const api: typeof chrome = (globalThis as unknown as { browser?: typeof chrome }).browser ?? chrome

export function call<T>(fn: (callback: (value: T) => void) => void): Promise<T> {
  return new Promise((resolve, reject) => fn((value) => {
    const error = api.runtime.lastError
    error ? reject(new Error(error.message)) : resolve(value)
  }))
}
