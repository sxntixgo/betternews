// expo-secure-store is a native module with no JS implementation under Jest.
// Credentials are covered by their own unit tests against this fake.
jest.mock('expo-secure-store', () => {
  const store = new Map();
  return {
    getItemAsync: jest.fn(async (k) => (store.has(k) ? store.get(k) : null)),
    setItemAsync: jest.fn(async (k, v) => void store.set(k, v)),
    deleteItemAsync: jest.fn(async (k) => void store.delete(k)),
    __store: store,
  };
});

// React 18+ requires this for act-based rendering; jest-expo does not set it.
global.IS_REACT_ACT_ENVIRONMENT = true;
