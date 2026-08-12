// Set one exact function's calling convention in a disposable analysis project.
// @category Nuve

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class SetFunctionCallingConvention extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 2) {
            throw new IllegalArgumentException(
                "expected exact fully qualified function name and calling convention"
            );
        }
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        int matches = 0;
        while (functions.hasNext()) {
            Function function = functions.next();
            if (!function.getName(true).equals(arguments[0])) {
                continue;
            }
            println("before: " + function.getPrototypeString(false, false));
            function.setCallingConvention(arguments[1]);
            println("after: " + function.getPrototypeString(false, false));
            matches++;
        }
        if (matches != 1) {
            throw new IllegalArgumentException(
                "expected one function, found " + matches + ": " + arguments[0]
            );
        }
    }
}
