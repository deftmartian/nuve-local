// List API-like strings and the functions that reference them.
// @category Nuve

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

public class ListApiEndpointXrefs extends GhidraScript {
    private static final String DEFAULT_PATTERN = "api/";

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length > 1) {
            printerr("Provide zero arguments or one Java regular expression");
            return;
        }

        Pattern pattern;
        try {
            pattern = Pattern.compile(args.length == 1 ? args[0] : DEFAULT_PATTERN);
        }
        catch (PatternSyntaxException error) {
            printerr("Invalid regular expression: " + error.getMessage());
            return;
        }

        Listing listing = currentProgram.getListing();
        ReferenceManager references = currentProgram.getReferenceManager();
        Map<String, Set<String>> ownersByValue = new TreeMap<>();
        Map<String, Set<String>> locationsByValue = new TreeMap<>();

        DataIterator dataItems = listing.getDefinedData(true);
        while (dataItems.hasNext() && !monitor.isCancelled()) {
            Data data = dataItems.next();
            Object rawValue = data.getValue();
            if (!(rawValue instanceof String)) {
                continue;
            }
            String value = (String) rawValue;
            if (!pattern.matcher(value).find()) {
                continue;
            }

            ownersByValue.computeIfAbsent(value, ignored -> new TreeSet<>());
            locationsByValue
                .computeIfAbsent(value, ignored -> new TreeSet<>())
                .add(data.getAddress().toString());

            // Inspect the string base and the exact regexp-match starts. Scanning
            // every byte can misattribute references to pooled adjacent strings.
            Set<Integer> offsets = new TreeSet<>();
            offsets.add(0);
            Matcher matcher = pattern.matcher(value);
            while (matcher.find()) {
                int start = matcher.start();
                offsets.add(start);
                if (start < value.length() && value.charAt(start) == '/') {
                    offsets.add(start + 1);
                }
            }
            for (int offset : offsets) {
                Address target = data.getAddress().add(offset);
                ReferenceIterator incoming = references.getReferencesTo(target);
                while (incoming.hasNext()) {
                    Reference reference = incoming.next();
                    Address from = reference.getFromAddress();
                    Function function = listing.getFunctionContaining(from);
                    String owner = function == null
                        ? "<no function> @ " + from
                        : function.getName(true) + " @ " + function.getEntryPoint();
                    ownersByValue.get(value).add(owner);
                }
            }
        }

        int referenced = 0;
        for (Map.Entry<String, Set<String>> entry : ownersByValue.entrySet()) {
            println("ENDPOINT " + quote(entry.getKey()));
            println("  DATA " + String.join(", ", locationsByValue.get(entry.getKey())));
            if (entry.getValue().isEmpty()) {
                println("  OWNER <no direct reference>");
                continue;
            }
            referenced++;
            for (String owner : entry.getValue()) {
                println("  OWNER " + owner);
            }
        }
        println(
            "SUMMARY strings=" + ownersByValue.size() + " directly_referenced=" + referenced
        );
    }

    private String quote(String value) {
        return "\""
            + value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
            + "\"";
    }
}
