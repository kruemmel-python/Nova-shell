package ai.novashell.app;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private EditText commandInput;
    private Button runButton;
    private TextView statusText;
    private TextView outputText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        commandInput = findViewById(R.id.command_input);
        runButton = findViewById(R.id.run_button);
        statusText = findViewById(R.id.status_text);
        outputText = findViewById(R.id.output_text);

        commandInput.setText("doctor");
        runButton.setOnClickListener(view -> submitCommand());
        loadBootstrapSummary();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void loadBootstrapSummary() {
        setBusy(true, getString(R.string.status_booting));
        executor.execute(() -> renderResult(callBridge("bootstrap_summary_json")));
    }

    private void submitCommand() {
        final String command = commandInput.getText().toString().trim();
        if (command.isEmpty()) {
            statusText.setText(R.string.status_empty);
            return;
        }
        setBusy(true, getString(R.string.status_running));
        executor.execute(() -> renderResult(callBridge("run_single_command_json", command)));
    }

    private void renderResult(final String payload) {
        runOnUiThread(() -> {
            outputText.setText(payload);
            setBusy(false, getString(R.string.status_ready));
        });
    }

    private String callBridge(String method, String... args) {
        try {
            Python py = Python.getInstance();
            PyObject bridge = py.getModule("nova_mobile_bridge");
            PyObject result = bridge.callAttr(method, (Object[]) args);
            return result == null ? "{}" : result.toString();
        } catch (Exception exc) {
            return "{\"ok\":false,\"error\":" + JSONObject.quote(exc.toString()) + "}";
        }
    }

    private void setBusy(final boolean busy, final String status) {
        runOnUiThread(() -> {
            runButton.setEnabled(!busy);
            statusText.setText(status);
        });
    }
}
