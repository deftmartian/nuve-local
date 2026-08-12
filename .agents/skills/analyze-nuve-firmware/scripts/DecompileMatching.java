// Decompile functions whose fully qualified names start with a requested prefix.
// @category Nuve

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DecompileMatching extends GhidraScript {
    private static final int TIMEOUT_SECONDS = 180;

    @Override
    protected void run() throws Exception {
        String[] prefixes = getScriptArgs();
        if (prefixes.length == 0) {
            printerr("Provide at least one fully qualified function or class prefix");
            return;
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        if (!decompiler.openProgram(currentProgram)) {
            printerr("Unable to open the current program in the decompiler");
            return;
        }

        int attempted = 0;
        int failed = 0;
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        while (functions.hasNext() && !monitor.isCancelled()) {
            Function function = functions.next();
            String name = function.getName(true);
            boolean selected = false;
            for (String prefix : prefixes) {
                if (name.startsWith(prefix)) {
                    selected = true;
                    break;
                }
            }
            if (!selected) {
                continue;
            }

            attempted++;
            println("===== " + name + " @ " + function.getEntryPoint() + " =====");
            DecompileResults result =
                decompiler.decompileFunction(function, TIMEOUT_SECONDS, monitor);
            if (!result.decompileCompleted() || result.getDecompiledFunction() == null) {
                failed++;
                println("DECOMPILE FAILED: " + result.getErrorMessage());
            }
            else {
                println(result.getDecompiledFunction().getC());
            }
        }
        decompiler.dispose();
        println("SUMMARY attempted=" + attempted + " failed=" + failed);
    }
}
