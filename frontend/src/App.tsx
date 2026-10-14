import { useEffect, useState } from "react";

type ConnectionStatus = "checking" | "connected" | "failed";

function App() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch(
          `${import.meta.env.VITE_API_BASE_URL}/health`,
          { signal: controller.signal },
        );

        if (!response.ok) {
          throw new Error("Health request failed");
        }

        const data = await response.json();

        if (data.status !== "ok") {
          throw new Error("Unexpected health response");
        }

        setStatus("connected");
      } catch {
        if (!controller.signal.aborted) {
          setStatus("failed");
        }
      }
    }

    void checkBackend();

    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>MedulaAPI</h1>
      <p role="status">
        {status === "checking" && "Checking backend…"}
        {status === "connected" && "Backend connected"}
        {status === "failed" && "Could not connect to backend"}
      </p>
    </main>
  );
}

export default App;