import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import react from "eslint-plugin-react";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,js}"],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      react,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react/no-danger": "error",
      "no-magic-numbers": [
        "error",
        { ignore: [-1, 0, 1], ignoreArrayIndexes: true, ignoreDefaultValues: true },
      ],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-magic-numbers": "off",
    },
  },
);
