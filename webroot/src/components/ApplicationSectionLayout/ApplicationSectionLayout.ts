//
//  ApplicationSectionLayout.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import {
    Component,
    Prop,
    Vue,
    toNative
} from 'vue-facing-decorator';
import InputButton from '@components/Forms/InputButton/InputButton.vue';
import InputSubmit from '@components/Forms/InputSubmit/InputSubmit.vue';
import MockPopulate from '@components/Forms/MockPopulate/MockPopulate.vue';
import AlertTriangleIcon from '@components/Icons/AlertTriangle/AlertTriangle.vue';
import { FormInput } from '@models/FormInput/FormInput.model';

@Component({
    name: 'ApplicationSectionLayout',
    components: {
        InputButton,
        InputSubmit,
        MockPopulate,
        AlertTriangleIcon,
    },
    emits: ['submit', 'continue', 'mock-populate', 'clear'],
})
class ApplicationSectionLayout extends Vue {
    @Prop({ required: true }) title!: string;
    @Prop({ default: '' }) intro?: string;
    @Prop({ default: '' }) compactType?: string;
    @Prop({ default: '' }) applicationId?: string;
    @Prop({ default: false }) isLoadError?: boolean;
    @Prop({ default: false }) isFormReady?: boolean;
    @Prop({ default: true }) isEditable?: boolean;
    @Prop({ default: false }) isNeedsAttention?: boolean;
    @Prop({ default: () => [] }) attentionNotes?: Array<string>;
    @Prop({ default: () => new FormInput() }) submitFormInput!: FormInput;
    @Prop({ default: '' }) saveLabel?: string;
    @Prop({ default: true }) isSaveEnabled?: boolean;
    @Prop({ default: false }) isSaveSuccessful?: boolean;
    @Prop({ default: false }) isMockPopulateEnabled?: boolean;

    //
    // Computed
    //
    get hasChecklistRoute(): boolean {
        return Boolean(this.compactType && this.applicationId);
    }

    get checklistRoute(): object {
        return {
            name: 'ApplicationChecklist',
            params: { compact: this.compactType, applicationId: this.applicationId },
        };
    }

    //
    // Methods
    //
    submit(): void {
        this.$emit('submit');
    }

    continueToNext(): void {
        this.$emit('continue');
    }

    mockPopulate(): void {
        this.$emit('mock-populate');
    }

    clearForm(): void {
        this.$emit('clear');
    }
}

export default toNative(ApplicationSectionLayout);

// export default ApplicationSectionLayout;
