import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

public class ClaudeTestRunner {
    public static void main(String[] args) throws Exception {
        run("com.acme.review.client.PythonComputeClientContextTest", "shouldStartWithoutRegistryWhenDiscoveryDisabled");
        run("com.acme.review.service.WebhookDedupServiceTest", "shouldFallbackToLocalLockWhenRedissonMissing");
    }

    private static void run(String className, String methodName) throws Exception {
        try {
            Class<?> testClass = Class.forName(className);
            Constructor<?> constructor = testClass.getDeclaredConstructor();
            constructor.setAccessible(true);
            Object instance = constructor.newInstance();
            Method method = testClass.getDeclaredMethod(methodName);
            method.setAccessible(true);
            method.invoke(instance);
            System.out.println(className + "#" + methodName + " PASSED");
        } catch (InvocationTargetException exception) {
            Throwable cause = exception.getCause();
            System.err.println(className + "#" + methodName + " FAILED");
            cause.printStackTrace();
            System.exit(1);
        }
    }
}
