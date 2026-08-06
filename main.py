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
            first_line = input("\nSen: ")
            stripped_first = first_line.strip()

            if not stripped_first:
                continue

            if stripped_first.lower() in {"çık", "exit", "quit", "kapat"}:
                runtime.shutdown()
                print("Jarvis güvenli şekilde kapatılıyor...")
                break

            if stripped_first.lower() in {"durum", "sistem durumu"}:
                print("\n" + runtime.status())
                continue

            # Çok satırlı görev girişi: kullanıcı boş satır veya "BITIR"
            # yazana kadar satırlar tek mesajda biriktirilir.
            lines = [first_line]
            while True:
                line = input("... ")
                if line.strip().upper() == "BITIR" or line.strip() == "":
                    break
                lines.append(line)

            prompt = "\n".join(lines).strip()

            if not prompt:
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