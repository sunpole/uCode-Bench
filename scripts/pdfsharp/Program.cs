// uCode .NET merge helper. No rendering, rescaling or color conversion.
// API reference pinned to the package used by this helper:
// https://github.com/empira/PDFsharp/tree/v6.2.4
using System.Text;
using System.Text.Json;
using PdfSharp.Pdf;
using PdfSharp.Pdf.IO;

try
{
    if (args.Length != 1)
        throw new ArgumentException("Usage: dotnet PdfSharpMerge.dll <manifest.json>");

    var request = JsonSerializer.Deserialize<MergeRequest>(
        File.ReadAllText(args[0], Encoding.UTF8),
        new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
        ?? throw new ArgumentException("The manifest must contain inputs and output");
    if (request.Inputs is null || request.Inputs.Length == 0)
        throw new ArgumentException("At least one input PDF is required");
    if (string.IsNullOrWhiteSpace(request.Output))
        throw new ArgumentException("An output PDF path is required");

    var output = Path.GetFullPath(request.Output);
    if (File.Exists(output) || Directory.Exists(output))
        throw new IOException("Output already exists; refusing to overwrite: " + output);
    if (!Directory.Exists(Path.GetDirectoryName(output)))
        throw new DirectoryNotFoundException("Output directory does not exist");

    var pathComparer = OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
    var sources = new List<string>(request.Inputs.Length);
    foreach (var input in request.Inputs)
    {
        if (string.IsNullOrWhiteSpace(input))
            throw new ArgumentException("Empty input PDF path");
        var source = Path.GetFullPath(input);
        if (!File.Exists(source))
            throw new FileNotFoundException("Input PDF does not exist", source);
        if (pathComparer.Equals(source, output))
            throw new ArgumentException("Output must differ from every input");
        sources.Add(source);
    }

    using var result = new PdfDocument();
    foreach (var source in sources)
    {
        using var imported = PdfReader.Open(source, PdfDocumentOpenMode.Import);
        foreach (var page in imported.Pages)
            result.AddPage(page);
    }

    var pageCount = result.PageCount;
    // FileMode.CreateNew protects existing results, including a race after the
    // initial existence check. Save(Stream) is used instead of Save(filename),
    // whose documented behavior would overwrite a pre-existing file.
    using (var stream = new FileStream(output, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None))
        result.Save(stream, closeStream: false);

    Console.WriteLine(JsonSerializer.Serialize(new
    {
        engine = "PDFsharp 6.2.4", inputs = sources.Count, pages = pageCount
    }));
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine($"{exception.GetType().Name}: {exception.Message}");
    return 1;
}

internal sealed record MergeRequest(string[]? Inputs, string? Output);
