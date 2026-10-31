// Safe, versioned Windows installation. Never modifies the portable source folder.
// Installed binaries: %LOCALAPPDATA%\uBrand\uCode-App\versions\vX.Y.Z\uCode\
// User data remains in %LOCALAPPDATA%\uBrand\uCode (not inside managed versions).
using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace UCode.Updater;

internal static class SafeInstaller
{
    private const long MaxPackage = 512L * 1024 * 1024;
    private const long MaxUncompressed = 1024L * 1024 * 1024;
    private const int MaxEntries = 15000;
    private static readonly HttpClient Client = new(new HttpClientHandler
    {
        AllowAutoRedirect = true,
        UseCookies = false,
    })
    { Timeout = TimeSpan.FromMinutes(4) };
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private sealed record InstallState(string current, string? previous);

    internal static string InstallRoot => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "uBrand", "uCode-App");

    private static string StatePath(string root) => Path.Combine(root, "install-state.json");

    private static bool IsWithin(string root, string path)
    {
        string parent = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        return Path.GetFullPath(path).StartsWith(parent, StringComparison.OrdinalIgnoreCase);
    }

    private static void RequireNoLinks(string path)
    {
        string full = Path.GetFullPath(path);
        for (string? item = full; item is not null; item = Path.GetDirectoryName(item))
        {
            if ((Directory.Exists(item) || File.Exists(item)) &&
                (File.GetAttributes(item) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Каталог содержит ссылку или перенаправление: установка отменена.");
            string? parent = Path.GetDirectoryName(item);
            if (parent is null || parent == item) break;
        }
    }

    private static void AssertRoot(string root)
    {
        string approved = Path.GetFullPath(InstallRoot);
        if (!Path.GetFullPath(root).Equals(approved, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Разрешён только выделенный каталог приложения.");
        RequireNoLinks(root);
    }

    private static InstallState? ReadState(string root)
    {
        string path = StatePath(root);
        if (!File.Exists(path)) return null;
        InstallState? result = JsonSerializer.Deserialize<InstallState>(File.ReadAllText(path, Encoding.UTF8));
        if (result is null) throw new InvalidDataException("Повреждён файл состояния установки.");
        Program.ParseVersion(result.current);
        if (result.previous is not null) Program.ParseVersion(result.previous);
        return result;
    }

    private static void WriteState(string root, InstallState state)
    {
        string tmp = StatePath(root) + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(tmp, JsonSerializer.Serialize(state, JsonOptions), new UTF8Encoding(false));
            File.Move(tmp, StatePath(root), overwrite: true);
        }
        finally { if (File.Exists(tmp)) File.Delete(tmp); }
    }

    private static string VersionFolder(string root, string version)
    {
        Program.ParseVersion(version);
        string path = Path.Combine(root, "versions", "v" + version);
        if (!IsWithin(root, path)) throw new InvalidDataException("Неверная версия в пути.");
        return path;
    }

    private static string Binary(string root, string version) =>
        Path.Combine(VersionFolder(root, version), "uCode", "uCode.exe");

    private static async Task<byte[]> DownloadBytes(Uri url, long maxBytes)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.UserAgent.Add(new ProductInfoHeaderValue("uCodeUpdater", "0.2.0"));
        using var result = await Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
        result.EnsureSuccessStatusCode();
        if (result.RequestMessage?.RequestUri?.Scheme != Uri.UriSchemeHttps)
            throw new InvalidDataException("Источник скачивания не HTTPS.");
        if (result.Content.Headers.ContentLength > maxBytes)
            throw new InvalidDataException("Файл превышает установленный лимит.");
        await using var stream = await result.Content.ReadAsStreamAsync();
        using var buffer = new MemoryStream();
        byte[] block = new byte[65536];
        while (true)
        {
            int n = await stream.ReadAsync(block);
            if (n == 0) break;
            if (buffer.Length + n > maxBytes) throw new InvalidDataException("Файл превышает лимит.");
            buffer.Write(block, 0, n);
        }
        return buffer.ToArray();
    }

    private static string ExpectedHash(string manifest, string filename)
    {
        foreach (string line in manifest.Replace("\r", "").Split('\n'))
        {
            Match m = Regex.Match(line.Trim(),
                @"^([a-fA-F0-9]{64})\s+\*?([A-Za-z0-9_.-]+)$",
                RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(200));
            if (m.Success && m.Groups[2].Value == filename)
                return m.Groups[1].Value.ToLowerInvariant();
        }
        throw new InvalidDataException("SHA256SUMS.txt не содержит контрольную сумму нужного пакета.");
    }

    private static void ExtractSafe(byte[] archiveBytes, string destination)
    {
        Directory.CreateDirectory(destination);
        using var input = new MemoryStream(archiveBytes, writable: false);
        using var archive = new ZipArchive(input, ZipArchiveMode.Read);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaxEntries)
            throw new InvalidDataException("Необычное число файлов в архиве.");
        long total = 0;
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            string path = entry.FullName.Replace('\\', '/');
            if (!path.StartsWith("uCode/", StringComparison.Ordinal) || path.Contains('\0') ||
                path.StartsWith("/", StringComparison.Ordinal) ||
                path.Split('/').Any(s => s == "." || s == ".." || s.Contains(':')))
                throw new InvalidDataException("Опасный путь внутри ZIP.");
            if (!seen.Add(path)) throw new InvalidDataException("Повтор имени внутри ZIP.");
            // Unix symlinks and Windows reparse points are forbidden.
            int unixType = (entry.ExternalAttributes >> 16) & 0xF000;
            if (unixType == 0xA000 || (entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Архив содержит ссылку.");
            total = checked(total + entry.Length);
            if (total > MaxUncompressed)
                throw new InvalidDataException("Архив превышает лимит распаковки.");
            string target = Path.GetFullPath(Path.Combine(destination, path.Replace('/', Path.DirectorySeparatorChar)));
            if (!IsWithin(destination, target))
                throw new InvalidDataException("Путь ZIP выходит за целевой каталог.");
            if (path.EndsWith("/", StringComparison.Ordinal))
            {
                Directory.CreateDirectory(target);
            }
            else
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                using var source = entry.Open();
                using var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write);
                source.CopyTo(output);
            }
        }
        if (!File.Exists(Path.Combine(destination, "uCode", "uCode.exe")) ||
            !File.Exists(Path.Combine(destination, "uCode", "uCode.Updater.exe")))
            throw new InvalidDataException("Отсутствуют исполняемые файлы uCode и независимого обновлятора.");
    }

    private static void Smoke(string binary)
    {
        var start = new ProcessStartInfo(binary)
        {
            WorkingDirectory = Path.GetDirectoryName(binary)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("--smoke");
        using var process = Process.Start(start) ?? throw new InvalidDataException("Новая версия не запускается.");
        Task<string> output = process.StandardOutput.ReadToEndAsync();
        Task<string> errors = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(120_000))
        {
            process.Kill(entireProcessTree: true);
            throw new InvalidDataException("Превышено время самопроверки новой версии.");
        }
        Task.WaitAll(output, errors);
        if (process.ExitCode != 0)
            throw new InvalidDataException("Новая версия не прошла проверку QR/PDF.");
        string last = output.Result.Split('\n', StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? "";
        using JsonDocument smoke = JsonDocument.Parse(last);
        JsonElement result = smoke.RootElement;
        if (result.GetProperty("status").GetString() != "PASS" ||
            result.GetProperty("pages").GetInt32() != 2 ||
            result.GetProperty("quality_status").GetString() != "LIMITED")
            throw new InvalidDataException("Новый PDF не прошёл структурную QA.");
    }

    internal static async Task<int> InstallAsync(string installed, bool accepted)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Установка поддерживается только в Windows.");
        if (!accepted) throw new InvalidOperationException("Требуется явное согласие на установку (--accept).");
        Program.ParseVersion(installed);
        string root = InstallRoot;
        AssertRoot(root);
        Directory.CreateDirectory(root);
        using var gate = new FileStream(Path.Combine(root, "installer.lock"), FileMode.OpenOrCreate,
            FileAccess.ReadWrite, FileShare.None);
        Console.WriteLine("STAGE:checking-release");
        // The source of truth is a stable, non-draft GitHub Release, never a CI preview.
        string releaseEndpoint = "https://api.github.com/repos/sunpole/uCode-Bench/releases/latest";
        byte[] metadata = await DownloadBytes(new Uri(releaseEndpoint), 256 * 1024);
        using var doc = JsonDocument.Parse(metadata);
        JsonElement release = doc.RootElement;
        string tag = release.GetProperty("tag_name").GetString() ?? "";
        if (release.GetProperty("draft").GetBoolean() || release.GetProperty("prerelease").GetBoolean() ||
            !Regex.IsMatch(tag, @"^v[0-9]+\.[0-9]+\.[0-9]+$"))
            throw new InvalidDataException("Разрешены только стабильные релизы.");
        string version = tag[1..];
        if (Program.ParseVersion(version).CompareTo(Program.ParseVersion(installed)) <= 0)
        {
            Console.WriteLine("Установка не нужна: нового стабильного релиза нет.");
            return 0;
        }
        InstallState? prior = ReadState(root);
        if (prior is not null && Program.ParseVersion(version).CompareTo(Program.ParseVersion(prior.current)) <= 0)
            throw new InvalidDataException("Установленная управляемая версия уже актуальна.");
        string releaseUrl = "https://github.com/sunpole/uCode-Bench/releases/download/" + tag + "/";
        string filename = "uCode-" + version + "-windows-x64.zip";
        if (release.GetProperty("html_url").GetString() !=
            "https://github.com/sunpole/uCode-Bench/releases/tag/" + tag)
            throw new InvalidDataException("Некорректный источник релиза.");

        long expectedSize = -1;
        bool hasChecksums = false;
        foreach (JsonElement asset in release.GetProperty("assets").EnumerateArray())
        {
            string name = asset.GetProperty("name").GetString() ?? "";
            string url = asset.GetProperty("browser_download_url").GetString() ?? "";
            if (name == filename && url == releaseUrl + filename)
                expectedSize = asset.GetProperty("size").GetInt64();
            if (name == "SHA256SUMS.txt" && url == releaseUrl + "SHA256SUMS.txt")
                hasChecksums = true;
        }
        if (!hasChecksums || expectedSize < 1024 || expectedSize > MaxPackage)
            throw new InvalidDataException("Не найдены проверяемый пакет и файл SHA-256.");
        Console.WriteLine("STAGE:downloading-checksums");
        string checksumText = Encoding.UTF8.GetString(
            await DownloadBytes(new Uri(releaseUrl + "SHA256SUMS.txt"), 32 * 1024));
        string expectedHash = ExpectedHash(checksumText, filename);
        Console.WriteLine("STAGE:downloading-package");
        byte[] archive = await DownloadBytes(new Uri(releaseUrl + filename), MaxPackage);
        Console.WriteLine("STAGE:verifying-sha256");
        if (archive.Length != expectedSize ||
            !CryptographicOperations.FixedTimeEquals(
                Convert.FromHexString(expectedHash),
                SHA256.HashData(archive)))
            throw new InvalidDataException("Размер или SHA-256 пакета не совпадает!");

        Directory.CreateDirectory(root);
        AssertRoot(root);
        string dest = VersionFolder(root, version);
        if (Directory.Exists(dest) || File.Exists(dest))
            throw new InvalidDataException("Папка целевой версии уже существует; не перезаписываем.");
        Directory.CreateDirectory(Path.Combine(root, "versions"));
        string staging = Path.Combine(root, ".stage-" + Guid.NewGuid().ToString("N"));
        try
        {
            Console.WriteLine("STAGE:extracting");
            ExtractSafe(archive, staging);
            Console.WriteLine("STAGE:smoke-test");
            Smoke(Path.Combine(staging, "uCode", "uCode.exe"));
            Directory.Move(staging, dest);
            // The immutable initial launcher is separate from versioned app files.
            string launcher = Path.Combine(root, "uCode.Updater.exe");
            if (!File.Exists(launcher))
            {
                string host = Environment.ProcessPath ?? "";
                if (!host.EndsWith("uCode.Updater.exe", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Невозможно создать launcher из непроверенного процесса.");
                File.Copy(host, launcher, overwrite: false);
            }
            // State switch is last. On failure, the previous version remains selected.
            WriteState(root, new InstallState(version, prior?.current));
            bool shortcut = EnsureDesktopShortcut(root, version);
            Console.WriteLine("STAGE:installed");
            Console.WriteLine(shortcut ? "DESKTOP_SHORTCUT_CREATED" : "DESKTOP_SHORTCUT_UNCHANGED");
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                status = "INSTALLED", version,
                installed_at = dest, previous = prior?.current,
                launcher = "uCode.Updater.exe --launch"
            }, JsonOptions));
            return 0;
        }
        finally
        {
            // Only the private temporary stage created by this invocation.
            if (Directory.Exists(staging)) Directory.Delete(staging, recursive: true);
        }
    }

    internal static void WaitForExit(int pid)
    {
        if (pid <= 4) throw new InvalidOperationException("Недопустимый PID приложения.");
        try
        {
            using var old = Process.GetProcessById(pid);
            if (!old.ProcessName.Equals("uCode", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("PID не принадлежит uCode.");
            if (!old.WaitForExit(120_000))
                throw new InvalidOperationException("Старая программа не закрылась; новая установлена без автозапуска.");
        }
        catch (ArgumentException)
        {
            // Old app already exited. No process is being terminated here.
        }
    }

    private static bool EnsureDesktopShortcut(string root, string version)
    {
        if (!OperatingSystem.IsWindows()) return false;
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrWhiteSpace(desktop)) return false;
        string path = Path.Combine(desktop, "uCode.lnk");
        if (File.Exists(path))
            path = Path.Combine(desktop, "uCode (автообновление).lnk");
        if (File.Exists(path)) return false; // Never overwrite a user's existing shortcut.
        try
        {
            Type? type = Type.GetTypeFromProgID("WScript.Shell");
            if (type is null) return false;
            dynamic shell = Activator.CreateInstance(type)!;
            dynamic shortcut = shell.CreateShortcut(path);
            shortcut.TargetPath = Path.Combine(root, "uCode.Updater.exe");
            shortcut.WorkingDirectory = root;
            shortcut.IconLocation = Binary(root, version) + ",0";
            shortcut.Description = "uCode — управляемый запуск с восстановлением версии";
            shortcut.Save();
            return true;
        }
        catch (Exception ex) when (ex is System.Runtime.InteropServices.COMException or
            InvalidOperationException or UnauthorizedAccessException or IOException)
        {
            Console.Error.WriteLine("Не удалось создать ярлык: " + ex.GetType().Name);
            return false;
        }
    }

    internal static int Rollback(bool accepted)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!accepted) throw new InvalidOperationException("Откат требует --accept.");
        string root = InstallRoot;
        AssertRoot(root);
        using var gate = new FileStream(Path.Combine(root, "installer.lock"), FileMode.OpenOrCreate,
            FileAccess.ReadWrite, FileShare.None);
        InstallState state = ReadState(root) ??
            throw new InvalidDataException("Нет управляемой установки.");
        if (state.previous is null || !File.Exists(Binary(root, state.previous)))
            throw new InvalidDataException("Предыдущая проверенная версия не найдена.");
        WriteState(root, new InstallState(state.previous, state.current));
        Console.WriteLine("ROLLBACK_OK " + state.previous);
        return 0;
    }

    internal static int Launch()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        string root = InstallRoot;
        AssertRoot(root);
        InstallState state = ReadState(root) ??
            throw new InvalidDataException("Сначала выполните управляемую установку.");
        string binary = Binary(root, state.current);
        RequireNoLinks(binary);
        if (!File.Exists(binary))
        {
            // Boot attempt failed: restore last known available version.
            if (state.previous is null || !File.Exists(Binary(root, state.previous)))
                throw new InvalidDataException("Текущий и резервный исполняемые файлы отсутствуют.");
            WriteState(root, new InstallState(state.previous, state.current));
            binary = Binary(root, state.previous);
            RequireNoLinks(binary);
        }
        var start = new ProcessStartInfo(binary)
        {
            WorkingDirectory = Path.GetDirectoryName(binary)!,
            UseShellExecute = false,
        };
        Process.Start(start);
        return 0;
    }

    internal static bool SelfTest()
    {
        using var temp = new TempDirectory();
        string root = temp.Path;
        string archivePath = System.IO.Path.Combine(root, "fixture.zip");
        using (var zip = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            void Add(string name, string contents)
            {
                var entry = zip.CreateEntry(name);
                using var w = new StreamWriter(entry.Open(), Encoding.UTF8);
                w.Write(contents);
            }
            Add("uCode/uCode.exe", "dummy");
            Add("uCode/uCode.Updater.exe", "dummy");
            Add("uCode/_internal/value.txt", "safe");
        }
        string output = System.IO.Path.Combine(root, "out");
        ExtractSafe(File.ReadAllBytes(archivePath), output);
        if (!File.Exists(System.IO.Path.Combine(output, "uCode", "_internal", "value.txt"))) return false;
        if (ExpectedHash(new string('a', 64) + "  example.zip\r\n", "example.zip") != new string('a', 64))
            return false;
        using (var zip = ZipFile.Open(archivePath, ZipArchiveMode.Update))
        {
            zip.CreateEntry("uCode/../../outside.txt");
        }
        try
        {
            ExtractSafe(File.ReadAllBytes(archivePath), System.IO.Path.Combine(root, "evil"));
            return false;
        }
        catch (InvalidDataException) { return true; }
    }

    private sealed class TempDirectory : IDisposable
    {
        internal readonly string Path = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(), "ucode-updater-test-" + Guid.NewGuid().ToString("N"));
        internal TempDirectory() => Directory.CreateDirectory(Path);
        public void Dispose() => Directory.Delete(Path, recursive: true);
    }
}
