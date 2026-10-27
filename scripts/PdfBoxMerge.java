// Local Java 8 helper for Apache PDFBox 3.x. No JSON dependency is needed.
// API: https://pdfbox.apache.org/3.0/migration.html
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.List;
import org.apache.pdfbox.io.IOUtils;
import org.apache.pdfbox.multipdf.PDFMergerUtility;

public final class PdfBoxMerge {
    private PdfBoxMerge() { }

    public static void main(String[] args) throws IOException {
        if (args.length != 2) {
            throw new IllegalArgumentException("Usage: PdfBoxMerge INPUTS.txt OUTPUT.pdf");
        }
        List<String> sources = Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8);
        if (sources.isEmpty()) {
            throw new IllegalArgumentException("The source manifest is empty");
        }
        PDFMergerUtility merger = new PDFMergerUtility();
        for (String source : sources) {
            if (source.isEmpty()) {
                throw new IllegalArgumentException("The source manifest contains an empty path");
            }
            Path input = Paths.get(source);
            if (!Files.isRegularFile(input)) {
                throw new IOException("Source PDF not found: " + source);
            }
            merger.addSource(input.toFile());
        }
        Path output = Paths.get(args[1]);
        try (OutputStream stream = Files.newOutputStream(output, StandardOpenOption.CREATE_NEW,
                                                        StandardOpenOption.WRITE)) {
            merger.setDestinationStream(stream);
            merger.mergeDocuments(IOUtils.createTempFileOnlyStreamCache());
        }
    }
}
