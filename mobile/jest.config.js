module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
  moduleNameMapper: {
    // Component tests render against a minimal react-native mock: real RN
    // ships untranspiled Flow that ts-jest cannot transform. Logic tests
    // never load react-native at runtime (type-only imports are elided),
    // so this mapping is inert for them.
    "^react-native$": "<rootDir>/src/testing/mockReactNative.ts",
  },
  transform: {
    "^.+\\.tsx?$": ["ts-jest", {
      tsconfig: { strict: true, esModuleInterop: true, jsx: "react",
        target: "es2020", module: "commonjs", moduleResolution: "node", skipLibCheck: true, types: ["jest","node"] }
    }]
  }
};
