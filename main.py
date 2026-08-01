from src.core.runtime import JarvisRuntime


def main() -> None:
    runtime = JarvisRuntime()
    runtime.boot()

    print("=== JARVIS Başlatıldı ===")
    print("Durum: SLEEPING — görev bekleniyor.")
    print("Durumu görmek için: durum")
    print("Kapatmak için: çık")

    while runtime.state != runtime.STOPPED:
        try:
            prompt = input("\nSen: ").strip()

            if not prompt:
                continue

            if prompt.lower() in {"çık", "exit", "quit", "kapat"}:
                runtime.shutdown()
                print("Jarvis güvenli şekilde kapatılıyor...")
                break

            if prompt.lower() in {"durum", "sistem durumu"}:
                print("\n" + runtime.status())
                continue

            print("\nJarvis uyandı. Görev çalışıyor...")

            response = runtime.execute(prompt)

            print("\nJarvis:")
            print(response)
            print("\nDurum: SLEEPING — yeni görev bekleniyor.")

        except KeyboardInterrupt:
            runtime.shutdown()
            print("\nJarvis güvenli şekilde kapatıldı.")
            break


if __name__ == "__main__":
    main()